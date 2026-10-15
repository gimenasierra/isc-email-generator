from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

from .isc_secrets import ISCSecretError, get_credentials


HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.api\.identitynow(?:-demo)?\.com$")
ENDPOINTS = {
    "standard": "/notification-template-defaults/v1",
    "custom": "/notification-templates/v1",
}
RESOURCE_LABELS = {
    "standard": "las plantillas estándar (/notification-template-defaults/v1)",
    "custom": "las plantillas personalizadas (/notification-templates/v1)",
    "publish": "la publicación de plantillas (/notification-templates/v1)",
}
PERMISSION_GUIDANCE = (
    "Estas APIs no publican un scope granular propio; revisá que el PAT tenga "
    "sp:scopes:all y que su usuario propietario tenga un nivel de acceso adecuado."
)


class ISCError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class ISCWriteUncertain(ISCError):
    """The client cannot know whether ISC persisted an interrupted POST."""


def normalize_api_base_url(value: str) -> str:
    raw = value.strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("La URL base no es válida.") from exc
    if parsed.scheme.lower() != "https":
        raise ValueError("La URL base debe usar HTTPS.")
    if parsed.username or parsed.password:
        raise ValueError("La URL base no puede incluir usuario ni contraseña.")
    if port is not None:
        raise ValueError("La URL base no puede incluir un puerto.")
    host = (parsed.hostname or "").lower()
    if not HOST_RE.fullmatch(host):
        raise ValueError("El host debe tener el formato tenant.api.identitynow.com o tenant.api.identitynow-demo.com.")
    if parsed.path not in ("", "/"):
        raise ValueError("La URL base no puede incluir rutas adicionales.")
    if parsed.query or parsed.fragment:
        raise ValueError("La URL base no puede incluir query ni fragmentos.")
    return f"https://{host}"


@dataclass
class CachedToken:
    access_token: str
    expires_at: float


class ISCClient:
    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        credentials: Callable[[str], tuple[str, str]] = get_credentials,
    ):
        self.client = client or httpx.Client(timeout=30.0, follow_redirects=False)
        self.now = now
        self.sleep = sleep
        self.credentials = credentials
        self._tokens: dict[str, CachedToken] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock(self, connection_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(connection_id, threading.Lock())

    def invalidate(self, connection_id: str) -> None:
        with self._lock(connection_id):
            self._tokens.pop(connection_id, None)

    def _request(self, method: str, url: str, *, uncertain_on_failure: bool = False, **kwargs: Any) -> httpx.Response:
        try:
            response = self.client.request(method, url, **kwargs)
        except httpx.ConnectError as exc:
            if uncertain_on_failure:
                raise ISCWriteUncertain("La conexión se interrumpió después de iniciar la publicación; el resultado debe comprobarse en ISC.") from exc
            raise ISCError("No se pudo conectar con ISC. Verificá la URL y la conectividad.") from exc
        except httpx.TimeoutException as exc:
            if uncertain_on_failure:
                raise ISCWriteUncertain("ISC no respondió después de enviar la publicación; el resultado debe comprobarse antes de reintentar.") from exc
            raise ISCError("ISC no respondió dentro del tiempo esperado.") from exc
        except httpx.HTTPError as exc:
            raise ISCError("Falló la comunicación segura con ISC.") from exc
        if response.is_redirect:
            raise ISCError("ISC respondió con una redirección. No se enviaron credenciales a otro host.")
        return response

    def token(self, connection: dict[str, Any], force: bool = False) -> str:
        connection_id = connection["id"]
        with self._lock(connection_id):
            cached = self._tokens.get(connection_id)
            if not force and cached and cached.expires_at - self.now() > 60:
                return cached.access_token
            try:
                client_id, client_secret = self.credentials(connection_id)
            except ISCSecretError as exc:
                raise ISCError(str(exc), 400) from exc
            if not client_id or not client_secret:
                raise ISCError("La conexión no tiene Client ID y Client Secret configurados.", 400)
            base_url = normalize_api_base_url(connection["api_base_url"])
            response = self._request(
                "POST",
                f"{base_url}/oauth/token",
                headers={"Accept": "application/json"},
                data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
            )
            if response.status_code in (400, 401):
                raise ISCError("ISC rechazó el Client ID o Client Secret.", 401)
            if response.status_code == 403:
                raise ISCError("ISC autenticó la solicitud pero denegó la emisión del token.", 403)
            if response.is_error:
                raise ISCError(f"ISC respondió HTTP {response.status_code} al autenticar.")
            try:
                payload = response.json()
                access_token = payload["access_token"]
                expires_in = max(1, int(payload.get("expires_in", 3600)))
            except (ValueError, KeyError, TypeError) as exc:
                raise ISCError("La respuesta de autenticación de ISC no es válida.") from exc
            if not isinstance(access_token, str) or not access_token:
                raise ISCError("ISC no devolvió un access_token válido.")
            self._tokens[connection_id] = CachedToken(access_token, self.now() + expires_in)
            return access_token

    def _retry_after(self, response: httpx.Response) -> float:
        value = response.headers.get("Retry-After", "1").strip()
        try:
            return max(0.0, min(float(value), 30.0))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(0.0, min(retry_at.timestamp() - self.now(), 30.0))
            except (TypeError, ValueError, OverflowError):
                return 1.0

    def _authorized_get(self, connection: dict[str, Any], path: str, params: dict[str, Any]) -> httpx.Response:
        base_url = normalize_api_base_url(connection["api_base_url"])
        retried_unauthorized = False
        rate_retries = 0
        while True:
            token = self.token(connection)
            response = self._request(
                "GET",
                f"{base_url}{path}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                params=params,
            )
            if response.status_code == 401 and not retried_unauthorized:
                self.invalidate(connection["id"])
                retried_unauthorized = True
                continue
            if response.status_code == 429 and rate_retries < 2:
                rate_retries += 1
                self.sleep(self._retry_after(response))
                continue
            return response

    def _check_response(self, response: httpx.Response, template_type: str) -> None:
        if response.status_code == 401:
            raise ISCError("ISC rechazó el token aun después de renovarlo.", 401)
        if response.status_code == 403:
            raise ISCError(
                f"Autenticación correcta, pero ISC denegó el acceso a {RESOURCE_LABELS[template_type]}. "
                f"{PERMISSION_GUIDANCE}",
                403,
            )
        if response.status_code == 429:
            raise ISCError("ISC continúa limitando las solicitudes después de los reintentos.", 429)
        if response.is_error:
            raise ISCError(f"ISC respondió HTTP {response.status_code} al consultar plantillas.")

    def list_templates(self, connection: dict[str, Any], template_type: str) -> list[dict[str, Any]]:
        if template_type not in ENDPOINTS:
            raise ISCError("El tipo de plantilla solicitado no es válido.", 400)
        limit, offset = 250, 0
        templates: list[dict[str, Any]] = []
        for _ in range(100):
            response = self._authorized_get(
                connection,
                ENDPOINTS[template_type],
                {"limit": limit, "offset": offset},
            )
            self._check_response(response, template_type)
            try:
                page = response.json()
            except ValueError as exc:
                raise ISCError("ISC devolvió una respuesta que no es JSON.") from exc
            if not isinstance(page, list) or any(not isinstance(item, dict) for item in page):
                raise ISCError("ISC devolvió una estructura de plantillas no reconocida.")
            templates.extend(page)
            total_header = response.headers.get("X-Total-Count")
            total = int(total_header) if total_header and total_header.isdigit() else None
            if len(page) < limit or (total is not None and len(templates) >= total):
                return templates
            offset += limit
        raise ISCError("La consulta excedió el límite de páginas permitido.")

    def find_template_matches(
        self,
        connection: dict[str, Any],
        template_type: str,
        key: str,
        medium: str,
        locale: str,
    ) -> list[dict[str, Any]]:
        """Resolve exact identity locally after querying the official collection endpoint."""
        return [
            template
            for template in self.list_templates(connection, template_type)
            if str(template.get("key", "")) == key
            and str(template.get("medium", "")) == medium
            and str(template.get("locale", "")) == locale
        ]

    def get_template_by_id(
        self,
        connection: dict[str, Any],
        template_type: str,
        template_id: str,
    ) -> dict[str, Any] | None:
        """Read one template by an already known ID without accepting arbitrary paths."""
        if template_type not in ENDPOINTS:
            raise ISCError("El tipo de plantilla solicitado no es válido.", 400)
        if not re.fullmatch(r"[A-Za-z0-9-]{1,128}", template_id):
            raise ISCError("El ID de plantilla guardado no es válido.", 400)
        response = self._authorized_get(connection, f"{ENDPOINTS[template_type]}/{template_id}", {})
        if response.status_code == 404:
            return None
        self._check_response(response, template_type)
        try:
            template = response.json()
        except ValueError as exc:
            raise ISCError("ISC devolvió una plantilla que no es JSON.") from exc
        if not isinstance(template, dict):
            raise ISCError("ISC devolvió una estructura de plantilla no reconocida.")
        return template

    def create_notification_template(self, connection: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        base_url = normalize_api_base_url(connection["api_base_url"])
        retried_unauthorized = False
        rate_retries = 0
        while True:
            token = self.token(connection)
            response = self._request(
                "POST",
                f"{base_url}{ENDPOINTS['custom']}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json=payload,
                uncertain_on_failure=True,
            )
            if response.status_code == 401 and not retried_unauthorized:
                self.invalidate(connection["id"])
                retried_unauthorized = True
                continue
            if response.status_code == 429 and rate_retries < 2:
                rate_retries += 1
                self.sleep(self._retry_after(response))
                continue
            break
        if response.status_code == 401:
            raise ISCError("ISC rechazó el token aun después de renovarlo.", 401)
        if response.status_code == 403:
            raise ISCError(
                f"Autenticación correcta, pero ISC denegó el acceso a {RESOURCE_LABELS['publish']}. "
                f"{PERMISSION_GUIDANCE}",
                403,
            )
        if response.status_code == 429:
            raise ISCError("ISC continúa limitando la publicación después de los reintentos.", 429)
        if response.is_error:
            message = ""
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = str(error.get("detail") or error.get("message") or "")
            except ValueError:
                pass
            suffix = f": {message[:500]}" if message else ""
            raise ISCError(f"ISC respondió HTTP {response.status_code} al publicar la plantilla{suffix}.", response.status_code)
        try:
            result = response.json()
        except ValueError as exc:
            raise ISCError("ISC aceptó la publicación pero devolvió una respuesta que no es JSON.") from exc
        if not isinstance(result, dict):
            raise ISCError("ISC aceptó la publicación pero devolvió una estructura no reconocida.")
        return result

    def test_connection(self, connection: dict[str, Any]) -> dict[str, Any]:
        self.token(connection, force=True)
        permissions: dict[str, str] = {}
        for template_type, path in ENDPOINTS.items():
            response = self._authorized_get(
                connection,
                path,
                {"limit": 1, "offset": 0},
            )
            if response.status_code == 403:
                permissions[template_type] = "forbidden"
            else:
                self._check_response(response, template_type)
                permissions[template_type] = "ok"
        return {
            "authenticated": True,
            "permissions": permissions,
            "message": "Autenticación correcta. "
            + " ".join(
                f"Acceso a {RESOURCE_LABELS[key]}: {'disponible' if value == 'ok' else 'denegado por ISC'}."
                for key, value in permissions.items()
            )
            + (f" {PERMISSION_GUIDANCE}" if "forbidden" in permissions.values() else ""),
        }


isc_client = ISCClient()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
