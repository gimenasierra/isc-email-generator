from __future__ import annotations

from copy import deepcopy
from collections import Counter
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .isc import ISCError, isc_client, normalize_api_base_url, utc_now_iso
from .date_translation import SUPPORTED_DATE_VARIABLES, is_spanish, prepare_spanish_date_body, restore_spanish_date_body
from .isc_secrets import ISCSecretError, credential_status, delete_credentials, set_credentials
from .models import AIConfig, AIConfigUpdate, AIConnectionTestRequest, AdaptRequest, BrandingConfig, DateTranslationUpdate, EditResultRequest, ImportRequest, ISCConnectionInput, ISCImportRequest, PublicationBatchConfirmRequest, PublicationBatchPrepareRequest, PublicationConfirmRequest, PublicationPrepareRequest, PublicationVerifyRequest, StyleGuideUpdate
from .prompt_rules import PromptRulesError, delete_style_guide, get_style_guide, save_style_guide
from .publication import prepare_item, publish_prepared, reverify_publication
from .providers.base import ProviderError
from .providers.base import TemplateContext
from .providers.registry import api_key_for, connection_state, key_configured, provider_for, save_api_key, set_connection_state, set_session_key
from .runtime import RUNTIME_SIGNATURE
from .store import (
    StoreError,
    editable_content,
    get_item,
    inspect_import,
    import_local_templates,
    import_isc_templates,
    load_project,
    save_project,
    summary,
    template_identity,
    adaptation_signature,
    is_config_outdated,
)
from .velocity import validate_velocity
from . import server_runtime


@asynccontextmanager
async def lifespan(_app: FastAPI):
    server_runtime.initialize()
    yield


app = FastAPI(title="ISC Email Generator API", version="0.1.0", lifespan=lifespan)
if not server_runtime.enabled():
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12)


class AdminUserCreateRequest(BaseModel):
    username: str
    temporary_password: str = Field(min_length=12)
    role: str = "user"


class AdminPasswordResetRequest(BaseModel):
    temporary_password: str = Field(min_length=12)


class AdminActiveRequest(BaseModel):
    active: bool


def _secure_cookies() -> bool:
    return os.getenv("ISC_EMAIL_GENERATOR_SECURE_COOKIES", "1").strip() != "0"


def _require_admin(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Se requiere un usuario administrador.")
    return user


@app.middleware("http")
async def server_authentication(request: Request, call_next):
    if not server_runtime.enabled() or not request.url.path.startswith("/api/"):
        return await call_next(request)
    if request.url.path in {"/api/health", "/api/auth/login"}:
        return await call_next(request)
    raw_session = request.cookies.get(server_runtime.SESSION_COOKIE, "")
    user = server_runtime.session_user(raw_session)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "La sesión no está autenticada o venció."})
    allowed_during_password_change = {"/api/auth/me", "/api/auth/logout", "/api/auth/change-password"}
    if user["must_change_password"] and request.url.path not in allowed_during_password_change:
        return JSONResponse(status_code=403, content={"detail": "Debe cambiar la contraseña temporal antes de continuar.", "code": "password_change_required"})
    if request.method not in {"GET", "HEAD", "OPTIONS"} and not server_runtime.validate_csrf(raw_session, request.headers.get("X-CSRF-Token", "")):
        return JSONResponse(status_code=403, content={"detail": "La validación CSRF falló."})
    request.state.user = user
    user_context = server_runtime.current_user_id.set(user["id"])
    expected_context = server_runtime.expected_project_version.set(None)
    saved_context = server_runtime.saved_project_version.set(None)
    style_context = server_runtime.expected_style_guide_version.set(None)
    request_metadata: dict[str, int] = {}
    metadata_context = server_runtime.request_metadata.set(request_metadata)
    version_header = request.headers.get("X-Project-Version", "").strip()
    if version_header:
        try:
            server_runtime.expected_project_version.set(int(version_header))
        except ValueError:
            server_runtime.current_user_id.reset(user_context)
            server_runtime.expected_project_version.reset(expected_context)
            server_runtime.saved_project_version.reset(saved_context)
            server_runtime.expected_style_guide_version.reset(style_context)
            server_runtime.request_metadata.reset(metadata_context)
            return JSONResponse(status_code=400, content={"detail": "X-Project-Version no es válido."})
    style_header = request.headers.get("X-Style-Guide-Version", "").strip()
    if style_header:
        try:
            server_runtime.expected_style_guide_version.set(int(style_header))
        except ValueError:
            server_runtime.current_user_id.reset(user_context)
            server_runtime.expected_project_version.reset(expected_context)
            server_runtime.saved_project_version.reset(saved_context)
            server_runtime.expected_style_guide_version.reset(style_context)
            server_runtime.request_metadata.reset(metadata_context)
            return JSONResponse(status_code=400, content={"detail": "X-Style-Guide-Version no es válido."})
    try:
        response = await call_next(request)
        saved_version = request_metadata.get("saved_project_version")
        if saved_version is not None:
            response.headers["X-Project-Version"] = str(saved_version)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and response.status_code < 400:
            server_runtime.audit("api.mutation", {"method": request.method, "path": request.url.path})
        return response
    finally:
        server_runtime.current_user_id.reset(user_context)
        server_runtime.expected_project_version.reset(expected_context)
        server_runtime.saved_project_version.reset(saved_context)
        server_runtime.expected_style_guide_version.reset(style_context)
        server_runtime.request_metadata.reset(metadata_context)


@app.exception_handler(server_runtime.ConcurrentUpdateError)
def concurrent_update_error(_request: Request, exc: server_runtime.ConcurrentUpdateError):
    return JSONResponse(status_code=409, content={"detail": str(exc), "code": "concurrent_update"})


@app.exception_handler(server_runtime.SecretUnavailableError)
def secret_unavailable_error(_request: Request, exc: server_runtime.SecretUnavailableError):
    return JSONResponse(status_code=503, content={"detail": str(exc), "code": "secrets_locked"})


@app.post("/api/auth/login")
def login(payload: LoginRequest, response: Response):
    try:
        user, token, csrf = server_runtime.authenticate(payload.username, payload.password)
    except server_runtime.AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    response.set_cookie(server_runtime.SESSION_COOKIE, token, httponly=True, secure=_secure_cookies(), samesite="lax", max_age=server_runtime.SESSION_HOURS * 3600, path="/")
    response.set_cookie(server_runtime.CSRF_COOKIE, csrf, httponly=False, secure=_secure_cookies(), samesite="lax", max_age=server_runtime.SESSION_HOURS * 3600, path="/")
    return {"user": user, "csrf_token": csrf}


@app.get("/api/auth/me")
def authenticated_user(request: Request):
    return {"user": request.state.user}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    server_runtime.logout(request.cookies.get(server_runtime.SESSION_COOKIE, ""))
    response.delete_cookie(server_runtime.SESSION_COOKIE, path="/")
    response.delete_cookie(server_runtime.CSRF_COOKIE, path="/")
    return {"ok": True}


@app.post("/api/auth/change-password")
def change_password(request: Request, payload: PasswordChangeRequest, response: Response):
    try:
        server_runtime.change_password(request.state.user["id"], payload.current_password, payload.new_password)
    except server_runtime.AuthenticationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response.delete_cookie(server_runtime.SESSION_COOKIE, path="/")
    response.delete_cookie(server_runtime.CSRF_COOKIE, path="/")
    return {"ok": True, "reauthenticate": True}


@app.get("/api/admin/users")
def list_users(request: Request):
    _require_admin(request)
    return {"users": server_runtime.admin_list_users()}


@app.post("/api/admin/users")
def create_user(request: Request, payload: AdminUserCreateRequest):
    _require_admin(request)
    try:
        return {"user": server_runtime.create_user(payload.username, payload.temporary_password, payload.role, True)}
    except server_runtime.AuthenticationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/users/{user_id}/reset-password")
def reset_user_password(user_id: str, request: Request, payload: AdminPasswordResetRequest):
    _require_admin(request)
    try:
        server_runtime.admin_reset_password(user_id, payload.temporary_password)
    except server_runtime.AuthenticationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@app.put("/api/admin/users/{user_id}/active")
def set_user_active(user_id: str, request: Request, payload: AdminActiveRequest):
    actor = _require_admin(request)
    if user_id == actor["id"] and not payload.active:
        raise HTTPException(status_code=400, detail="No puede desactivar su propia cuenta.")
    try:
        server_runtime.admin_set_active(user_id, payload.active)
    except server_runtime.AuthenticationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


def safe_download_filename(value: object, fallback: str) -> str:
    """Return an ASCII filename safe for a quoted Content-Disposition header."""
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip())
    candidate = candidate.strip("._-")[:120]
    return candidate or fallback


def unsafe_velocity_changes(validation) -> list[str]:
    def describe(values: list[str]) -> str:
        counts = Counter(values)
        rendered = [f"{value} (×{count})" if count > 1 else value for value, count in counts.items()]
        visible = ", ".join(rendered[:6])
        return visible + (f", y {len(rendered) - 6} más" if len(rendered) > 6 else "")

    problems: list[str] = []
    if validation.missing_variables:
        problems.append(f"{len(validation.missing_variables)} referencia(s) Velocity eliminada(s): {describe(validation.missing_variables)}")
    if validation.added_variables:
        problems.append(f"{len(validation.added_variables)} referencia(s) Velocity agregada(s): {describe(validation.added_variables)}")
    if validation.missing_directives:
        problems.append(f"{len(validation.missing_directives)} directiva(s) eliminada(s): {describe(validation.missing_directives)}")
    if validation.added_directives:
        problems.append(f"{len(validation.added_directives)} directiva(s) agregada(s): {describe(validation.added_directives)}")
    if validation.directive_order_changed:
        problems.append("las directivas Velocity cambiaron de orden")
    if validation.modified_protected_blocks:
        problems.append(
            f"{len(validation.modified_protected_blocks)} bloque(s) determinista(s) de traducción de fecha fueron modificados o eliminados"
        )
    return problems


def body_looks_truncated(original: str, result: str) -> bool:
    original_size = len(original.strip())
    result_size = len(result.strip())
    return original_size >= 300 and result_size < original_size * 0.6


def validate_ai_adaptation(
    subject: str,
    body: str,
    adaptation,
    old_client_name: str,
    protected_blocks: list[str] | tuple[str, ...] | None = None,
):
    validation = validate_velocity(
        subject + "\n" + body,
        adaptation.subject + "\n" + adaptation.body,
        old_client_name,
        protected_blocks,
    )
    unsafe_changes = unsafe_velocity_changes(validation)
    if body_looks_truncated(body, adaptation.body):
        unsafe_changes.append("el cuerpo parece truncado o perdió una parte sustancial del contenido")
    return validation, unsafe_changes


@app.exception_handler(StoreError)
async def store_error_handler(_, exc: StoreError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(ISCError)
async def isc_error_handler(_, exc: ISCError):
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.get("/api/health")
def health():
    return {"status": "ok", "runtime_signature": RUNTIME_SIGNATURE, "server_mode": server_runtime.enabled(), "secrets_available": server_runtime.secrets_available()}


def ai_status(project_id: str, settings: AIConfig):
    selected = provider_for(settings)
    return {
        "id": settings.provider,
        "name": selected.name,
        "model": settings.model,
        "base_url": settings.base_url,
        "simulated": selected.is_simulated,
        "key_configured": key_configured(project_id, settings.provider),
        "connection": connection_state(project_id, settings.provider),
    }


def find_isc_connection(project: dict, connection_id: str) -> dict:
    for connection in project.get("isc_connections", []):
        if connection["id"] == connection_id:
            return connection
    raise HTTPException(status_code=404, detail="No se encontró la conexión ISC.")


def invalidate_preparations(project: dict, connection_id: str | None = None) -> None:
    for item in project.get("items", []):
        preparation = item.get("publication_preparation")
        if preparation and (connection_id is None or preparation.get("connection", {}).get("id") == connection_id):
            item["publication_preparation"] = None


def project_style_hash(project: dict) -> str:
    return str(project.get("style_guide_hash", ""))


def isc_connection_view(connection: dict) -> dict:
    try:
        client_configured, secret_configured = credential_status(connection["id"])
    except ISCSecretError:
        client_configured = secret_configured = False
    return {
        "id": connection["id"],
        "name": connection["name"],
        "environment": connection["environment"],
        "api_base_url": connection["api_base_url"],
        "client_id_configured": client_configured,
        "secret_configured": secret_configured,
        "status": connection.get("status", "not_tested"),
        "status_message": connection.get("status_message", "Conexión sin probar."),
    }


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    project = load_project(project_id)
    return {
        "project_id": project["project_id"],
        "project_version": int(project.get("project_version", 0)),
        "filename": project.get("filename", ""),
        "config": project["config"],
        "templates": [summary(item, project["config"], project["ai_config"], project_style_hash(project)).model_dump() for item in project["items"]],
        "ai_config": project["ai_config"],
        "provider": ai_status(project_id, AIConfig.model_validate(project["ai_config"])),
    }


@app.get("/api/projects/{project_id}/isc-connections")
def get_isc_connections(project_id: str):
    project = load_project(project_id)
    return {"connections": [isc_connection_view(connection) for connection in project["isc_connections"]]}


@app.post("/api/projects/{project_id}/isc-connections")
def create_isc_connection(project_id: str, request: ISCConnectionInput):
    project = load_project(project_id)
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Ingresá un nombre para la conexión.")
    try:
        base_url = normalize_api_base_url(request.api_base_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection_id = uuid4().hex
    try:
        set_credentials(connection_id, request.client_id, request.client_secret)
    except ISCSecretError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection = {
        "id": connection_id,
        "name": name,
        "environment": request.environment,
        "api_base_url": base_url,
        "status": "not_tested",
        "status_message": "Conexión guardada; probala antes de consultar plantillas.",
    }
    project["isc_connections"].append(connection)
    save_project(project_id, project)
    isc_client.invalidate(connection_id)
    return isc_connection_view(connection)


@app.put("/api/projects/{project_id}/isc-connections/{connection_id}")
def update_isc_connection(project_id: str, connection_id: str, request: ISCConnectionInput):
    project = load_project(project_id)
    connection = find_isc_connection(project, connection_id)
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Ingresá un nombre para la conexión.")
    try:
        base_url = normalize_api_base_url(request.api_base_url)
        set_credentials(connection_id, request.client_id, request.client_secret)
    except (ValueError, ISCSecretError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection.update(
        name=name,
        environment=request.environment,
        api_base_url=base_url,
        status="not_tested",
        status_message="La configuración cambió; probá nuevamente la conexión.",
    )
    invalidate_preparations(project, connection_id)
    save_project(project_id, project)
    isc_client.invalidate(connection_id)
    return isc_connection_view(connection)


@app.delete("/api/projects/{project_id}/isc-connections/{connection_id}")
def delete_isc_connection(project_id: str, connection_id: str):
    project = load_project(project_id)
    connection = find_isc_connection(project, connection_id)
    try:
        delete_credentials(connection_id)
    except ISCSecretError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    project["isc_connections"] = [item for item in project["isc_connections"] if item["id"] != connection_id]
    invalidate_preparations(project, connection_id)
    save_project(project_id, project)
    isc_client.invalidate(connection_id)
    return {"deleted_id": connection_id, "name": connection["name"]}


@app.post("/api/projects/{project_id}/isc-connections/{connection_id}/test")
def test_isc_connection(project_id: str, connection_id: str):
    project = load_project(project_id)
    connection = find_isc_connection(project, connection_id)
    try:
        result = isc_client.test_connection(connection)
    except ISCError as exc:
        connection["status"] = "error"
        connection["status_message"] = str(exc)
        save_project(project_id, project)
        raise
    has_all_permissions = all(value == "ok" for value in result["permissions"].values())
    connection["status"] = "connected" if has_all_permissions else "limited"
    connection["status_message"] = result["message"]
    save_project(project_id, project)
    return {**result, "connection": isc_connection_view(connection)}


@app.get("/api/projects/{project_id}/isc-connections/{connection_id}/templates")
def list_isc_templates(project_id: str, connection_id: str, template_type: str):
    project = load_project(project_id)
    connection = find_isc_connection(project, connection_id)
    templates = isc_client.list_templates(connection, template_type)
    read_at = utc_now_iso()
    candidates = []
    for template in templates:
        # ISC returns EMAIL, SLACK and TEAMS records in the same collection.
        # This application adapts email HTML, so keep the remote request
        # unfiltered and select the supported medium locally.
        if str(template.get("medium", "")).casefold() != "email":
            continue
        canonical = json.dumps(template, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        candidates.append({
            "selection_id": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "name": str(template.get("name", template.get("displayName", "Sin nombre"))),
            "key": str(template.get("key", "")),
            "medium": str(template.get("medium", "")),
            "locale": str(template.get("locale", "")),
            "template": template,
        })
    return {
        "connection": isc_connection_view(connection),
        "template_type": template_type,
        "read_at": read_at,
        "templates": candidates,
    }


@app.post("/api/projects/{project_id}/isc-connections/{connection_id}/import")
def import_from_isc(project_id: str, connection_id: str, request: ISCImportRequest):
    project = load_project(project_id)
    connection = find_isc_connection(project, connection_id)
    result = import_isc_templates(
        project,
        request.templates,
        {
            "connection_id": connection["id"],
            "connection_name": connection["name"],
            "api_base_url": connection["api_base_url"],
            "environment": connection["environment"],
            "template_type": request.template_type,
        },
        request.duplicate_strategy,
    )
    save_project(project_id, project)
    return {**result, "templates": [summary(item, project["config"], project["ai_config"], project_style_hash(project)).model_dump() for item in project["items"]]}


@app.post("/api/projects/{project_id}/import")
def import_templates(project_id: str, request: ImportRequest):
    project = load_project(project_id)
    requested_files = [(entry.filename, entry.data) for entry in request.files]
    if not requested_files:
        requested_files = [(request.filename, request.data)]
    valid_files: list[tuple[str, list[dict]]] = []
    rejected_files: list[dict[str, str]] = []
    for filename, data in requested_files:
        try:
            valid_files.append((filename, inspect_import(data)))
        except StoreError as exc:
            rejected_files.append({"filename": filename, "error": str(exc)})
    result = import_local_templates(project, valid_files, request.duplicate_strategy)
    if valid_files:
        names = [filename for filename, _ in valid_files]
        project["filename"] = names[0] if len(names) == 1 else f"{len(names)} archivos JSON"
    save_project(project_id, project)
    return {
        **result,
        "valid_files": [{"filename": filename, "templates": len(templates)} for filename, templates in valid_files],
        "rejected_files": rejected_files,
        "templates": [summary(item, project["config"], project["ai_config"], project_style_hash(project)).model_dump() for item in project["items"]],
    }


@app.put("/api/projects/{project_id}/config")
def put_config(project_id: str, config: BrandingConfig):
    project = load_project(project_id)
    project["config"] = config.model_dump()
    invalidate_preparations(project)
    save_project(project_id, project)
    return {"config": project["config"]}


@app.get("/api/projects/{project_id}/style-guide")
def get_project_style_guide(project_id: str):
    try:
        return get_style_guide(project_id)
    except PromptRulesError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.put("/api/projects/{project_id}/style-guide")
def put_project_style_guide(project_id: str, request: StyleGuideUpdate):
    try:
        guide = save_style_guide(project_id, request.content, request.filename)
    except PromptRulesError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    project = load_project(project_id)
    project["style_guide_hash"] = guide["hash"]
    invalidate_preparations(project)
    save_project(project_id, project)
    return guide


@app.delete("/api/projects/{project_id}/style-guide")
def delete_project_style_guide(project_id: str):
    try:
        guide = delete_style_guide(project_id)
    except PromptRulesError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    project = load_project(project_id)
    project["style_guide_hash"] = ""
    invalidate_preparations(project)
    save_project(project_id, project)
    return guide


@app.put("/api/projects/{project_id}/ai-config")
def put_ai_config(project_id: str, request: AIConfigUpdate):
    project = load_project(project_id)
    settings = AIConfig(provider=request.provider, model=request.model.strip(), base_url=request.base_url.strip())
    project["ai_config"] = settings.model_dump()
    invalidate_preparations(project)
    if request.api_key and settings.provider != "simulated":
        save_api_key(project_id, settings.provider, request.api_key)
    set_connection_state(project_id, settings.provider, "not_tested", "La configuración cambió; probá la conexión antes de generar.")
    save_project(project_id, project)
    return {"ai_config": settings.model_dump(), "provider": ai_status(project_id, settings)}


@app.post("/api/projects/{project_id}/ai-config/test")
def test_ai_connection(project_id: str, request: AIConnectionTestRequest):
    settings = AIConfig(provider=request.provider, model=request.model.strip(), base_url=request.base_url.strip())
    if request.api_key:
        set_session_key(project_id, settings.provider, request.api_key)
    selected = provider_for(settings)
    try:
        result = selected.test_connection(settings, api_key_for(project_id, settings.provider))
    except ProviderError as exc:
        set_connection_state(project_id, settings.provider, "error", str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    set_connection_state(project_id, settings.provider, "connected", result.message)
    return {"status": "connected", "message": result.message, "provider": ai_status(project_id, settings)}


def date_translation_state(item: dict, config: BrandingConfig) -> dict:
    result = item.get("result")
    language_supported = is_spanish(config.target_language)
    record = item.get("date_translation") if isinstance(item.get("date_translation"), dict) else {}
    applied = bool(item.get("protected_velocity_blocks")) or bool(record.get("applied"))
    available: list[str] = []
    variables = [str(value) for value in record.get("variables", []) if value in SUPPORTED_DATE_VARIABLES]
    if isinstance(result, dict) and language_supported:
        try:
            _, _, _, result_body = editable_content(result)
            inspected = prepare_spanish_date_body(
                result_body,
                list(SUPPORTED_DATE_VARIABLES),
                config.target_language,
            )
            if applied and not variables:
                variables = list(inspected.transformed_variables)
            elif not applied:
                available = list(inspected.transformed_variables)
        except StoreError:
            pass
    return {
        "applied": applied,
        "removable": bool(record.get("removable")) if applied else False,
        "variables": variables,
        "available_variables": available,
        "language_supported": language_supported,
    }


@app.get("/api/projects/{project_id}/templates/{internal_id}")
def get_template(project_id: str, internal_id: str):
    project = load_project(project_id)
    item = get_item(project, internal_id)
    _, _, original_subject, original_body = editable_content(item["original"])
    result_subject = result_body = None
    if item.get("result"):
        _, _, result_subject, result_body = editable_content(item["result"])
    return {
        "internal_id": internal_id,
        "original": item["original"],
        "result": item.get("result"),
        "original_subject": original_subject,
        "original_body": original_body,
        "result_subject": result_subject,
        "result_body": result_body,
        "validation": item.get("validation"),
        "protected_velocity_blocks": item.get("protected_velocity_blocks", []),
        "date_translation": date_translation_state(item, BrandingConfig.model_validate(project["config"])),
        "actions": item.get("actions", []),
        "provenance": item.get("provenance"),
        "config_outdated": is_config_outdated(item, project["config"], project["ai_config"], project_style_hash(project)),
        "publication_preparation": item.get("publication_preparation"),
        "publication_history": item.get("publication_history", []),
    }


@app.delete("/api/projects/{project_id}/templates/{internal_id}")
def delete_template(project_id: str, internal_id: str):
    project = load_project(project_id)
    item = get_item(project, internal_id)
    project["items"] = [candidate for candidate in project["items"] if candidate["internal_id"] != internal_id]
    if not project["items"]:
        project["filename"] = ""
    save_project(project_id, project)
    return {
        "deleted_id": internal_id,
        "name": str(item["original"].get("name", item["original"].get("displayName", "Sin nombre"))),
        "templates": [summary(candidate, project["config"], project["ai_config"], project_style_hash(project)).model_dump() for candidate in project["items"]],
    }


@app.delete("/api/projects/{project_id}/templates")
def clear_templates(project_id: str):
    project = load_project(project_id)
    deleted = len(project["items"])
    project["items"] = []
    project["filename"] = ""
    save_project(project_id, project)
    return {"deleted": deleted, "templates": []}


@app.post("/api/projects/{project_id}/adapt")
def adapt_template(project_id: str, request: AdaptRequest):
    project = load_project(project_id)
    item = get_item(project, request.internal_id)
    config = BrandingConfig.model_validate(project["config"])
    if config.mode == "guide" and not get_style_guide(project_id)["configured"]:
        raise HTTPException(status_code=409, detail="Guardá una guía Markdown antes de generar en modo guía.")
    ai_config = AIConfig.model_validate(project["ai_config"])
    selected_provider = provider_for(ai_config)
    subject_field, body_field, subject, body = editable_content(item["original"])
    api_key = api_key_for(project_id, ai_config.provider)
    context = TemplateContext(
        name=str(item["original"].get("name", item["original"].get("displayName", ""))),
        key=str(item["original"].get("key", "")),
        locale=str(item["original"].get("locale", "")),
        project_id=project_id,
    )
    try:
        adaptation = selected_provider.adapt(
            subject,
            body,
            config,
            ai_config,
            api_key,
            context,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    validation, unsafe_changes = validate_ai_adaptation(
        subject,
        body,
        adaptation,
        config.old_client_name,
        (),
    )
    if unsafe_changes:
        raise HTTPException(
            status_code=502,
            detail=(
                "La IA devolvió una adaptación insegura y no se guardó: "
                + "; ".join(unsafe_changes)
                + ". Probá nuevamente o elegí otro modelo."
            ),
        )
    result = deepcopy(item["original"])
    result[subject_field] = adaptation.subject
    result[body_field] = adaptation.body
    item["result"] = result
    item["validation"] = validation.model_dump()
    item["adaptation_baseline"] = {"subject": subject, "body": body}
    item["protected_velocity_blocks"] = []
    item["date_translation"] = None
    item["actions"] = [
        f"Proveedor: {selected_provider.name} ({ai_config.model or 'sin modelo'})",
        *adaptation.changes,
    ]
    item["adaptation_config_signature"] = adaptation_signature(project["config"], project["ai_config"], project_style_hash(project))
    item["publication_preparation"] = None
    save_project(project_id, project)
    return get_template(project_id, request.internal_id)


@app.put("/api/projects/{project_id}/templates/{internal_id}/result")
def edit_result(project_id: str, internal_id: str, request: EditResultRequest):
    project = load_project(project_id)
    item = get_item(project, internal_id)
    if not item.get("result"):
        raise HTTPException(status_code=409, detail="Primero genere una adaptación.")
    subject_field, body_field, original_subject, original_body = editable_content(item["original"])
    config = BrandingConfig.model_validate(project["config"])
    baseline = item.get("adaptation_baseline") or {
        "subject": original_subject,
        "body": original_body,
    }
    validation = validate_velocity(
        str(baseline.get("subject", original_subject)) + "\n" + str(baseline.get("body", original_body)),
        request.subject + "\n" + request.body,
        config.old_client_name,
        item.get("protected_velocity_blocks") or [],
    ).model_dump()
    structural_fields = (
        "missing_variables",
        "added_variables",
        "missing_directives",
        "added_directives",
        "directive_order_changed",
        "modified_protected_blocks",
    )
    if request.editor_mode == "visual" and any(validation.get(field) for field in structural_fields):
        raise HTTPException(
            status_code=409,
            detail=(
                "La edición visual alteró variables, directivas o bloques protegidos de Velocity. "
                "No se guardó ningún cambio. Restaurá el contenido bloqueado o usá el modo HTML para una reparación avanzada."
            ),
        )
    item["result"][subject_field] = request.subject
    item["result"][body_field] = request.body
    item["validation"] = validation
    item["publication_preparation"] = None
    save_project(project_id, project)
    return get_template(project_id, internal_id)


@app.put("/api/projects/{project_id}/templates/{internal_id}/date-translation")
def update_date_translation(project_id: str, internal_id: str, request: DateTranslationUpdate):
    project = load_project(project_id)
    item = get_item(project, internal_id)
    if not item.get("result"):
        raise HTTPException(status_code=409, detail="Primero generá una adaptación.")
    config = BrandingConfig.model_validate(project["config"])
    if not is_spanish(config.target_language):
        raise HTTPException(status_code=409, detail="La traducción determinista de fechas solo está disponible cuando el idioma de destino es español.")

    _, body_field, original_subject, original_body = editable_content(item["original"])
    _, _, result_subject, result_body = editable_content(item["result"])
    baseline = item.get("adaptation_baseline") or {"subject": original_subject, "body": original_body}
    record = item.get("date_translation") if isinstance(item.get("date_translation"), dict) else {}

    if request.enabled:
        current_validation = item.get("validation") or {}
        unsafe_fields = (
            "missing_variables",
            "added_variables",
            "missing_directives",
            "added_directives",
            "directive_order_changed",
            "modified_protected_blocks",
        )
        if any(current_validation.get(field) for field in unsafe_fields):
            raise HTTPException(status_code=409, detail="Corregí primero los cambios inseguros de Velocity de la adaptación.")
        if item.get("protected_velocity_blocks") or record.get("applied"):
            return get_template(project_id, internal_id)
        variables = list(SUPPORTED_DATE_VARIABLES)
        prepared_result = prepare_spanish_date_body(result_body, variables, config.target_language)
        if not prepared_result.replacements:
            raise HTTPException(status_code=409, detail="La adaptación no contiene fechas visibles compatibles para traducir.")
        # La adaptación ya fue validada contra el original. Para proteger todas las
        # apariciones visibles —incluidas repeticiones autorizadas—, el estado seguro
        # inmediatamente anterior al postproceso pasa a ser la línea base editable.
        previous_baseline = deepcopy(baseline)
        prepared_baseline = prepare_spanish_date_body(result_body, variables, config.target_language)
        validation = validate_velocity(
            result_subject + "\n" + prepared_baseline.body,
            result_subject + "\n" + prepared_result.body,
            config.old_client_name,
            prepared_baseline.protected_blocks,
        )
        if unsafe_velocity_changes(validation):
            raise HTTPException(status_code=409, detail="No se pudo aplicar la traducción sin alterar la validación de Velocity.")
        baseline = {"subject": result_subject, "body": prepared_baseline.body}
        item["result"][body_field] = prepared_result.body
        item["protected_velocity_blocks"] = list(prepared_baseline.protected_blocks)
        item["date_translation"] = {
            "applied": True,
            "removable": True,
            "variables": list(prepared_result.transformed_variables),
            "result_replacements": [replacement.__dict__ for replacement in prepared_result.replacements],
            "previous_baseline": previous_baseline,
        }
        item["validation"] = validation.model_dump()
        action = "Fechas traducidas de forma determinista: " + ", ".join(prepared_result.transformed_variables)
        item["actions"] = [entry for entry in item.get("actions", []) if not entry.startswith("Fechas traducidas de forma determinista:")]
        item["actions"].append(action)
    else:
        if not record.get("applied"):
            return get_template(project_id, internal_id)
        if not record.get("removable"):
            raise HTTPException(status_code=409, detail="Esta adaptación usa bloques de fecha anteriores que no pueden quitarse automáticamente.")
        try:
            restored_result = restore_spanish_date_body(result_body, list(record.get("result_replacements") or []))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        previous_baseline = record.get("previous_baseline") if isinstance(record.get("previous_baseline"), dict) else None
        restored_baseline = previous_baseline or {"subject": original_subject, "body": original_body}
        validation = validate_velocity(
            str(restored_baseline.get("subject", original_subject)) + "\n" + str(restored_baseline.get("body", original_body)),
            result_subject + "\n" + restored_result,
            config.old_client_name,
        )
        baseline = restored_baseline
        item["result"][body_field] = restored_result
        item["protected_velocity_blocks"] = []
        item["date_translation"] = None
        item["validation"] = validation.model_dump()
        item["actions"] = [entry for entry in item.get("actions", []) if not entry.startswith("Fechas traducidas de forma determinista:")]

    item["adaptation_baseline"] = baseline
    item["publication_preparation"] = None
    save_project(project_id, project)
    return get_template(project_id, internal_id)


@app.get("/api/projects/{project_id}/templates/{internal_id}/download")
def download_result(project_id: str, internal_id: str):
    project = load_project(project_id)
    item = get_item(project, internal_id)
    if not item.get("result"):
        raise HTTPException(status_code=409, detail="Primero genere una adaptación.")
    validation = item.get("validation") or {}
    structural_changes = any(
        validation.get(field)
        for field in ("missing_variables", "added_variables", "missing_directives", "added_directives", "directive_order_changed", "modified_protected_blocks")
    )
    if structural_changes:
        raise HTTPException(
            status_code=409,
            detail="La descarga está bloqueada porque la adaptación cambió variables, directivas o bloques deterministas de fecha. Corregí el resultado y volvé a validarlo.",
        )
    original = item["original"]
    filename = f"{safe_download_filename(original.get('key') or original.get('name'), internal_id)}-adapted.json"
    return JSONResponse(
        content=item["result"],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def prepare_publication_for_item(project_id: str, project: dict, item: dict, connection: dict) -> dict:
    if is_config_outdated(item, project["config"], project["ai_config"], project_style_hash(project)):
        raise ISCError("La adaptación corresponde a una configuración anterior. Volvé a generarla o revisala antes de preparar la publicación.", 409)
    original = item["original"]
    identity = {
        "key": str(original.get("key", "")),
        "medium": str(original.get("medium", "")),
        "locale": str(original.get("locale", "")),
    }
    known_custom_ids: list[str] = []
    for candidate in project.get("items", []):
        for publication in candidate.get("publication_history", []):
            if publication.get("connection", {}).get("id") != connection.get("id"):
                continue
            if any(str(publication.get("identity", {}).get(field, "")) != value for field, value in identity.items()):
                continue
            for source in (publication.get("response"), publication.get("verification")):
                template_id = source.get("id") if isinstance(source, dict) else None
                if isinstance(template_id, str) and template_id and template_id not in known_custom_ids:
                    known_custom_ids.append(template_id)
    preparation = prepare_item(
        item,
        project["config"],
        connection,
        isc_client,
        known_custom_ids,
    )
    save_project(project_id, project)
    return preparation


@app.post("/api/projects/{project_id}/templates/{internal_id}/publication/prepare")
def prepare_publication(project_id: str, internal_id: str, request: PublicationPrepareRequest):
    project = load_project(project_id)
    item = get_item(project, internal_id)
    connection = find_isc_connection(project, request.connection_id)
    return prepare_publication_for_item(project_id, project, item, connection)


@app.get("/api/projects/{project_id}/templates/{internal_id}/publication/download")
def download_publication_payload(project_id: str, internal_id: str):
    project = load_project(project_id)
    item = get_item(project, internal_id)
    preparation = item.get("publication_preparation")
    if not preparation:
        raise HTTPException(status_code=409, detail="Primero prepará la publicación para el destino elegido.")
    connection = find_isc_connection(project, preparation["connection"]["id"])
    from .publication import preparation_is_current
    if not preparation_is_current(preparation, item, project["config"], connection):
        item["publication_preparation"] = None
        save_project(project_id, project)
        raise HTTPException(status_code=409, detail="La preparación quedó desactualizada. Prepará nuevamente.")
    filename = f"{safe_download_filename(preparation['identity'].get('key'), internal_id)}-isc-publication-payload.json"
    return JSONResponse(
        content=preparation["payload"],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/projects/{project_id}/templates/{internal_id}/publication/publish")
def publish_publication(project_id: str, internal_id: str, request: PublicationConfirmRequest):
    project = load_project(project_id)
    item = get_item(project, internal_id)
    connection = find_isc_connection(project, request.connection_id)
    return publish_prepared(project_id, project, item, connection, request.preparation_id, isc_client, save_project)


@app.post("/api/projects/{project_id}/templates/{internal_id}/publication/verify")
def verify_publication(project_id: str, internal_id: str, request: PublicationVerifyRequest):
    project = load_project(project_id)
    item = get_item(project, internal_id)
    connection = find_isc_connection(project, request.connection_id)
    return reverify_publication(project_id, project, item, connection, request.publication_id, isc_client, save_project)


@app.post("/api/projects/{project_id}/publication/batches/prepare")
def prepare_publication_batch(project_id: str, request: PublicationBatchPrepareRequest):
    project = load_project(project_id)
    connection = find_isc_connection(project, request.connection_id)
    results = []
    seen: set[str] = set()
    ready_identities: dict[tuple[str, str, str], str] = {}
    for internal_id in request.internal_ids:
        if internal_id in seen:
            continue
        seen.add(internal_id)
        try:
            item = get_item(project, internal_id)
            identity = template_identity(item["original"])
            if identity in ready_identities:
                raise ISCError(
                    "Otra copia local con el mismo key + medium + locale ya está incluida en este lote. "
                    "Prepará y publicá solamente una de las copias por vez.",
                    409,
                )
            preparation = prepare_publication_for_item(project_id, project, item, connection)
            ready_identities[identity] = internal_id
            results.append({"internal_id": internal_id, "status": "ready", "preparation": preparation})
        except (ISCError, StoreError) as exc:
            results.append({"internal_id": internal_id, "status": "blocked", "error": str(exc)})
    return {"connection": isc_connection_view(connection), "items": results}


@app.post("/api/projects/{project_id}/publication/batches/publish")
def publish_publication_batch(project_id: str, request: PublicationBatchConfirmRequest):
    project = load_project(project_id)
    connection = find_isc_connection(project, request.connection_id)
    results = []
    seen: set[str] = set()
    published_identities: set[tuple[str, str, str]] = set()
    for entry in request.items:
        internal_id = str(entry.get("internal_id", ""))
        preparation_id = str(entry.get("preparation_id", ""))
        if not internal_id or internal_id in seen:
            continue
        seen.add(internal_id)
        try:
            item = get_item(project, internal_id)
            identity = template_identity(item["original"])
            if identity in published_identities:
                raise ISCError(
                    "Se bloqueó una segunda copia local con el mismo key + medium + locale dentro del lote.",
                    409,
                )
            record = publish_prepared(project_id, project, item, connection, preparation_id, isc_client, save_project)
            published_identities.add(identity)
            results.append({"internal_id": internal_id, "status": record["status"], "publication": record})
        except (ISCError, StoreError) as exc:
            results.append({"internal_id": internal_id, "status": "failed", "error": str(exc)})
    return {
        "connection": isc_connection_view(connection),
        "transactional": False,
        "items": results,
    }


FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if (FRONTEND_DIST / "index.html").exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
else:
    @app.get("/", include_in_schema=False)
    def frontend_not_built():
        return JSONResponse(
            status_code=503,
            content={
                "detail": "El frontend no está compilado. Ejecute `npm.cmd install` y `npm.cmd run build` dentro de frontend/."
            },
        )

