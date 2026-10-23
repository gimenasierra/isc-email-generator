from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from .isc import ISCClient, ISCError, ISCWriteUncertain
from .store import editable_content


STRUCTURAL_VALIDATION_FIELDS = (
    "missing_variables",
    "added_variables",
    "missing_directives",
    "added_directives",
    "directive_order_changed",
    "modified_protected_blocks",
)
PUBLISHABLE_FIELDS = (
    "key",
    "name",
    "medium",
    "locale",
    "subject",
    "body",
    "from",
    "replyTo",
    "description",
)
VERIFY_FIELDS = ("key", "medium", "locale", "subject", "body", "from", "replyTo")
PUBLISHED_PENDING_VERIFICATION = "published_pending_verification"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_hash(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def connection_signature(connection: dict[str, Any]) -> str:
    return canonical_hash(
        {
            "id": connection["id"],
            "name": connection["name"],
            "environment": connection["environment"],
            "api_base_url": connection["api_base_url"],
        }
    )


def local_signature(item: dict[str, Any], project_config: dict[str, Any]) -> str:
    return canonical_hash({"result": item.get("result"), "config": project_config})


def has_structural_changes(validation: dict[str, Any] | None) -> bool:
    validation = validation or {}
    return any(validation.get(field) for field in STRUCTURAL_VALIDATION_FIELDS)


def resolve_destination(
    client: ISCClient,
    connection: dict[str, Any],
    key: str,
    medium: str,
    locale: str,
    known_custom_ids: list[str] | tuple[str, ...] = (),
) -> tuple[str, dict[str, Any]]:
    custom = client.find_template_matches(connection, "custom", key, medium, locale)
    if len(custom) > 1:
        raise ISCError(
            f"El destino devolvió {len(custom)} personalizaciones para la misma combinación key + medium + locale. No se eligió ninguna.",
            409,
        )
    if len(custom) == 1:
        return "replace_custom", custom[0]
    direct_matches: list[dict[str, Any]] = []
    get_by_id = getattr(client, "get_template_by_id", None)
    if callable(get_by_id):
        for template_id in dict.fromkeys(known_custom_ids):
            if not template_id:
                continue
            candidate = get_by_id(connection, "custom", template_id)
            if candidate is None:
                continue
            if (
                str(candidate.get("key", "")) == key
                and str(candidate.get("medium", "")) == medium
                and str(candidate.get("locale", "")) == locale
            ):
                direct_matches.append(candidate)
    unique_direct = {str(candidate.get("id", "")): candidate for candidate in direct_matches}
    if len(unique_direct) > 1:
        raise ISCError(
            "El destino devolvió más de una personalización conocida para la misma combinación key + medium + locale.",
            409,
        )
    if len(unique_direct) == 1:
        return "replace_custom", next(iter(unique_direct.values()))
    defaults = client.find_template_matches(connection, "standard", key, medium, locale)
    if len(defaults) > 1:
        raise ISCError(
            f"El destino devolvió {len(defaults)} plantillas estándar para la misma combinación key + medium + locale. No se eligió ninguna.",
            409,
        )
    if not defaults:
        raise ISCError(
            "No existe en el destino una personalización ni una plantilla estándar con la combinación exacta key + medium + locale.",
            409,
        )
    return "create_from_default", defaults[0]


def build_payload(destination: dict[str, Any], result: dict[str, Any], mode: str) -> dict[str, Any]:
    _, _, subject, body = editable_content(result)
    payload: dict[str, Any] = {}
    for field in PUBLISHABLE_FIELDS:
        if field in destination:
            payload[field] = deepcopy(destination[field])
    payload.update(
        key=str(destination.get("key", "")),
        medium=str(destination.get("medium", "")),
        locale=str(destination.get("locale", "")),
        subject=subject,
        body=body,
    )
    # Some exports expose the JSON property as varFrom. TemplateDto's wire name
    # is `from`; normalize it without copying unrelated source metadata.
    if "from" not in payload and "varFrom" in destination:
        payload["from"] = deepcopy(destination["varFrom"])
    if mode == "replace_custom" and isinstance(destination.get("id"), str) and destination["id"]:
        payload["id"] = destination["id"]
    return payload


def reference_warnings(result: dict[str, Any], config: dict[str, Any], validation: dict[str, Any] | None, connection: dict[str, Any]) -> list[str]:
    _, _, subject, body = editable_content(result)
    content = subject + "\n" + body
    warnings: list[str] = []
    repeated = (validation or {}).get("repeated_variables", [])
    if repeated:
        visible = ", ".join(dict.fromkeys(repeated))
        warnings.append(f"Variables Velocity existentes repetidas adicionalmente para presentación: {visible}")
    for reference in (validation or {}).get("pending_old_client_references", []):
        warnings.append(f"Referencia pendiente al cliente anterior: {reference}")
    old_logo = str(config.get("old_logo_url", "")).strip()
    new_logo = str(config.get("new_logo_url", "")).strip()
    if old_logo and old_logo in content:
        warnings.append("El resultado todavía contiene la URL del logo anterior.")
    if new_logo and new_logo not in content:
        warnings.append("La URL del logo nuevo configurada no aparece en el resultado.")
    for label, mappings in (("correo", config.get("email_mappings", [])), ("URL", config.get("url_mappings", []))):
        for mapping in mappings:
            source = str(mapping.get("source", "")).strip()
            target = str(mapping.get("target", "")).strip()
            if source and target and source in content:
                warnings.append(f"Quedó una referencia de {label} pendiente: {source}")
    destination_host = (urlsplit(str(connection.get("api_base_url", ""))).hostname or "").lower()
    destination_tenant = destination_host.split(".api.", 1)[0]
    for match in re.finditer(r"https://([a-z0-9.-]*identitynow(?:-demo)?\.com)\b", content, re.IGNORECASE):
        hardcoded_host = match.group(1).lower()
        if destination_tenant and not hardcoded_host.startswith(destination_tenant + "."):
            warnings.append(f"URL hardcodeada posiblemente ajena al tenant destino: https://{hardcoded_host}")
    return list(dict.fromkeys(warnings))


def prepare_item(
    item: dict[str, Any],
    project_config: dict[str, Any],
    connection: dict[str, Any],
    client: ISCClient,
    known_custom_ids: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    if not item.get("result"):
        raise ISCError("La notificación todavía no tiene una adaptación revisada.", 409)
    if has_structural_changes(item.get("validation")):
        raise ISCError("La adaptación cambió variables o directivas Velocity y no puede prepararse para publicación.", 409)
    original = item["original"]
    key = str(original.get("key", ""))
    medium = str(original.get("medium", ""))
    locale = str(original.get("locale", ""))
    if not key or not medium or not locale:
        raise ISCError("La plantilla local no tiene key, medium y locale completos.", 409)
    mode, destination = resolve_destination(
        client, connection, key, medium, locale, known_custom_ids
    )
    payload = build_payload(destination, item["result"], mode)
    preparation = {
        "preparation_id": uuid4().hex,
        "prepared_at": utc_now_iso(),
        "connection": {
            "id": connection["id"],
            "name": connection["name"],
            "environment": connection["environment"],
            "api_base_url": connection["api_base_url"],
        },
        "identity": {"key": key, "medium": medium, "locale": locale},
        "name": str(destination.get("name") or original.get("name") or key),
        "mode": mode,
        "target_current": deepcopy(destination),
        "target_snapshot_hash": canonical_hash(destination),
        "payload": payload,
        "warnings": reference_warnings(item["result"], project_config, item.get("validation"), connection),
        "validation": deepcopy(item.get("validation")),
        "local_signature": local_signature(item, project_config),
        "connection_signature": connection_signature(connection),
    }
    item["publication_preparation"] = preparation
    return preparation


def preparation_is_current(
    preparation: dict[str, Any],
    item: dict[str, Any],
    project_config: dict[str, Any],
    connection: dict[str, Any],
) -> bool:
    return (
        preparation.get("local_signature") == local_signature(item, project_config)
        and preparation.get("connection_signature") == connection_signature(connection)
        and preparation.get("connection", {}).get("id") == connection.get("id")
    )


def payload_matches(payload: dict[str, Any], actual: dict[str, Any]) -> tuple[bool, list[str]]:
    differences = [field for field in VERIFY_FIELDS if payload.get(field) != actual.get(field)]
    return not differences, differences


def find_published_with_eventual_consistency(
    client: ISCClient,
    connection: dict[str, Any],
    identity: dict[str, str],
    known_custom_ids: list[str] | tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Retry read-after-write because ISC collections may not expose a new custom template immediately."""
    matches: list[dict[str, Any]] = []
    sleep = getattr(client, "sleep", lambda _seconds: None)
    for delay in (0, 1, 2, 4, 8):
        if delay:
            sleep(delay)
        matches = client.find_template_matches(
            connection,
            "custom",
            identity["key"],
            identity["medium"],
            identity["locale"],
        )
        if matches:
            break
        get_by_id = getattr(client, "get_template_by_id", None)
        if callable(get_by_id):
            direct_matches = []
            for template_id in dict.fromkeys(known_custom_ids):
                if not template_id:
                    continue
                candidate = get_by_id(connection, "custom", template_id)
                if candidate is not None and all(
                    str(candidate.get(field, "")) == str(identity[field])
                    for field in ("key", "medium", "locale")
                ):
                    direct_matches.append(candidate)
            unique = {str(candidate.get("id", "")): candidate for candidate in direct_matches}
            if unique:
                matches = list(unique.values())
                break
    return matches


def publish_prepared(
    project_id: str,
    project: dict[str, Any],
    item: dict[str, Any],
    connection: dict[str, Any],
    preparation_id: str,
    client: ISCClient,
    save_project,
) -> dict[str, Any]:
    preparation = item.get("publication_preparation")
    if not preparation or preparation.get("preparation_id") != preparation_id:
        raise ISCError("La preparación indicada ya no está disponible. Prepará nuevamente la publicación.", 409)
    if not preparation_is_current(preparation, item, project["config"], connection):
        item["publication_preparation"] = None
        save_project(project_id, project)
        raise ISCError("La adaptación, la configuración o la conexión cambió desde la preparación. Prepará nuevamente.", 409)

    # A retry must never issue a second POST for the same reviewed payload.
    # Pending/uncertain writes are resolved through the verification endpoint.
    duplicate = next(
        (
            record
            for record in reversed(item.get("publication_history", []))
            if record.get("connection", {}).get("id") == connection.get("id")
            and record.get("local_signature") == preparation.get("local_signature")
            and record.get("status") in {"published_pending_verification", "published_verified", "published_with_differences", "result_unconfirmed"}
        ),
        None,
    )
    if duplicate:
        raise ISCError(
            "Esta versión ya tiene una publicación aceptada o incierta para el tenant. Usá Volver a comprobar; no se realizó otro POST.",
            409,
        )

    identity = preparation["identity"]
    current_mode, current_destination = resolve_destination(
        client,
        connection,
        identity["key"],
        identity["medium"],
        identity["locale"],
        [
            str(preparation.get("target_current", {}).get("id", "")),
        ],
    )
    if current_mode != preparation["mode"] or canonical_hash(current_destination) != preparation["target_snapshot_hash"]:
        item["publication_preparation"] = None
        save_project(project_id, project)
        raise ISCError("La plantilla de destino cambió desde la preparación. Volvé a preparar y revisá la comparación actualizada.", 409)

    backup = {
        "backup_id": uuid4().hex,
        "saved_at": utc_now_iso(),
        "connection": deepcopy(preparation["connection"]),
        "identity": deepcopy(identity),
        "state": "customization" if current_mode == "replace_custom" else "no_customization",
        "template": deepcopy(current_destination),
    }
    item.setdefault("publication_backups", []).append(backup)
    save_project(project_id, project)

    response: dict[str, Any] | None = None
    uncertain_reason = ""
    try:
        response = client.create_notification_template(connection, preparation["payload"])
    except ISCWriteUncertain as exc:
        uncertain_reason = str(exc)

    verification: dict[str, Any] | None = None
    differences: list[str] = []
    write_acknowledged = response is not None
    status = PUBLISHED_PENDING_VERIFICATION if write_acknowledged else "result_unconfirmed"
    try:
        response_id = response.get("id") if isinstance(response, dict) else None
        custom_matches = find_published_with_eventual_consistency(
            client,
            connection,
            identity,
            [response_id] if isinstance(response_id, str) and response_id else [],
        )
        if len(custom_matches) == 1:
            verification = custom_matches[0]
            matches, differences = payload_matches(preparation["payload"], verification)
            status = "published_verified" if matches else "published_with_differences"
        else:
            if write_acknowledged:
                id_text = f" y devolvió el ID {response_id}" if isinstance(response_id, str) and response_id else ""
                uncertain_reason = uncertain_reason or (
                    f"ISC aceptó la publicación{id_text}. La personalización todavía no apareció "
                    "en las consultas de verificación; podés volver a comprobarla sin volver a publicar."
                )
            else:
                uncertain_reason = uncertain_reason or "No se encontró una única personalización al verificar el destino."
    except ISCError as exc:
        if write_acknowledged:
            uncertain_reason = uncertain_reason or (
                f"ISC aceptó la publicación, pero no se pudo completar la verificación de lectura: {exc}"
            )
        else:
            uncertain_reason = uncertain_reason or f"No se pudo verificar el destino: {exc}"

    record = {
        "publication_id": uuid4().hex,
        "published_at": utc_now_iso(),
        "status": status,
        "connection": deepcopy(preparation["connection"]),
        "identity": deepcopy(identity),
        "preparation_id": preparation_id,
        "backup_id": backup["backup_id"],
        "write_acknowledged": write_acknowledged,
        "local_signature": preparation["local_signature"],
        "payload": deepcopy(preparation["payload"]),
        "response": deepcopy(response),
        "verification": deepcopy(verification),
        "differences": differences,
        "message": uncertain_reason,
    }
    try:
        from . import server_runtime

        if server_runtime.enabled():
            record["published_by"] = server_runtime.require_user_id()
            record["payload_hash"] = canonical_hash(preparation["payload"])
            record["idempotency_key"] = canonical_hash(
                {
                    "user": record["published_by"],
                    "tenant": connection.get("api_base_url"),
                    "identity": identity,
                    "payload_hash": record["payload_hash"],
                }
            )
            server_runtime.audit(
                "isc.published",
                {
                    "connection_id": connection.get("id"),
                    "tenant": connection.get("api_base_url"),
                    "identity": identity,
                    "payload_hash": record["payload_hash"],
                    "status": status,
                },
                project_key=project_id,
            )
    except ImportError:
        pass
    item.setdefault("publication_history", []).append(record)
    item["publication_preparation"] = None
    save_project(project_id, project)
    return record


def reverify_publication(
    project_id: str,
    project: dict[str, Any],
    item: dict[str, Any],
    connection: dict[str, Any],
    publication_id: str,
    client: ISCClient,
    save_project,
) -> dict[str, Any]:
    record = next(
        (entry for entry in item.get("publication_history", []) if entry.get("publication_id") == publication_id),
        None,
    )
    if not record:
        raise ISCError("No se encontró el registro local de esa publicación.", 404)
    if record.get("connection", {}).get("id") != connection.get("id"):
        raise ISCError("La publicación pertenece a otra conexión ISC.", 409)

    identity = record["identity"]
    known_ids = []
    for source in (record.get("response"), record.get("verification")):
        template_id = source.get("id") if isinstance(source, dict) else None
        if isinstance(template_id, str) and template_id:
            known_ids.append(template_id)
    matches = find_published_with_eventual_consistency(client, connection, identity, known_ids)
    write_acknowledged = bool(record.get("write_acknowledged")) or bool(
        isinstance(record.get("response"), dict) and record["response"].get("id")
    )
    if len(matches) != 1:
        record["status"] = PUBLISHED_PENDING_VERIFICATION if write_acknowledged else "result_unconfirmed"
        record["message"] = (
            f"La comprobación encontró {len(matches)} personalizaciones para la combinación exacta. "
            + (
                "La publicación ya había sido aceptada por ISC y no se realizó una nueva escritura."
                if write_acknowledged
                else "El resultado de la escritura sigue sin poder confirmarse y no se realizó una nueva escritura."
            )
        )
        record["verification"] = None
        record["differences"] = []
    else:
        verification = matches[0]
        expected = record.get("payload") or record.get("response")
        if not isinstance(expected, dict):
            raise ISCError("El registro anterior no conserva contenido suficiente para comparar el resultado.", 409)
        matched, differences = payload_matches(expected, verification)
        record["status"] = "published_verified" if matched else "published_with_differences"
        record["message"] = ""
        record["verification"] = deepcopy(verification)
        record["differences"] = differences
    record["verified_at"] = utc_now_iso()
    save_project(project_id, project)
    return record

