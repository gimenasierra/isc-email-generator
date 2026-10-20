from __future__ import annotations

import json
import re
import hashlib
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .date_translation import SUPPORTED_DATE_VARIABLES, canonicalize_generated_date_blocks
from .models import AIConfig, BrandingConfig, TemplateSummary
from .paths import BACKEND_DIR, state_path
from .prompt_rules import get_style_guide
from .velocity import validate_velocity


DATA_DIR = state_path("data", development_default=BACKEND_DIR / "data")
SUBJECT_FIELDS = ("subject", "emailSubject", "title")
BODY_FIELDS = ("body", "emailBody", "content", "message")


class StoreError(ValueError):
    pass


def safe_project_id(project_id: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]", "-", project_id).strip("-")[:80]
    if not value:
        raise StoreError("El identificador del proyecto no es válido.")
    return value


def _path(project_id: str) -> Path:
    return DATA_DIR / f"{safe_project_id(project_id)}.json"


def load_project(project_id: str) -> dict[str, Any]:
    path = _path(project_id)
    if not path.exists():
        return {"project_id": safe_project_id(project_id), "filename": "", "config": BrandingConfig().model_dump(), "ai_config": AIConfig().model_dump(), "isc_connections": [], "items": []}
    project = json.loads(path.read_text(encoding="utf-8"))
    raw_config = project.get("config", {})
    legacy_reference = isinstance(raw_config, dict) and raw_config.get("mode") == "reference"
    project["config"] = BrandingConfig.model_validate(raw_config).model_dump()
    if legacy_reference and "## 4. Componentes reutilizables" in str(raw_config.get("additional_instructions", "")):
        project["config"]["additional_instructions"] = (
            "Conservar la firma original cuando exista y utilizar la firma configurada solamente cuando la plantilla no tenga una. "
            "No agregar una segunda firma. No inventar información de negocio, soporte, URLs ni variables."
        )
    signature = str(project["config"].get("signature", ""))
    looks_like_instructions = (
        "Adaptar todo el texto visible" in signature
        and "Apache Velocity" in signature
        and "Aplicar la estructura visual" in signature
    )
    if looks_like_instructions and not str(project["config"].get("additional_instructions", "")).strip():
        project["config"]["additional_instructions"] = signature
        project["config"]["signature"] = ""
    project["ai_config"] = AIConfig.model_validate(project.get("ai_config", {})).model_dump()
    project["style_guide_hash"] = get_style_guide(project_id)["hash"]
    project.setdefault("isc_connections", [])
    for item in project.setdefault("items", []):
        item.setdefault("publication_preparation", None)
        item.setdefault("publication_backups", [])
        item.setdefault("publication_history", [])
        for publication in item["publication_history"]:
            response = publication.get("response")
            response_id = response.get("id") if isinstance(response, dict) else None
            if publication.get("status") == "result_unconfirmed" and isinstance(response_id, str) and response_id:
                publication["status"] = "published_pending_verification"
                publication["write_acknowledged"] = True
                publication["message"] = (
                    f"ISC aceptó la publicación y devolvió el ID {response_id}. La verificación de lectura sigue pendiente; "
                    "podés volver a comprobarla sin volver a publicar."
                )
        item.setdefault("adaptation_baseline", None)
        item.setdefault("protected_velocity_blocks", [])
        item.setdefault("date_translation", None)
        if isinstance(item.get("validation"), dict):
            item["validation"].setdefault("repeated_variables", [])
            item["validation"].setdefault("directive_order_changed", False)
            item["validation"].setdefault("modified_protected_blocks", [])
    if _migrate_saved_date_blocks(project):
        save_project(project_id, project)
    return project


def save_project(project_id: str, project: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(project_id)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def field_name(template: dict[str, Any], candidates: tuple[str, ...]) -> str | None:
    return next((candidate for candidate in candidates if candidate in template and isinstance(template[candidate], str)), None)


def inspect_import(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        templates = [data]
    elif isinstance(data, list):
        templates = data
    else:
        raise StoreError("Estructura no reconocida: se esperaba un objeto JSON o un array de objetos.")
    if not templates:
        raise StoreError("El array JSON está vacío.")
    for index, item in enumerate(templates):
        if not isinstance(item, dict):
            raise StoreError(f"El elemento {index + 1} no es un objeto JSON.")
        subject_field = field_name(item, SUBJECT_FIELDS)
        body_field = field_name(item, BODY_FIELDS)
        if not subject_field or not body_field:
            identity = ", ".join(
                part
                for part in (
                    f"nombre: {item.get('name')}" if item.get("name") else "",
                    f"key: {item.get('key')}" if item.get("key") else "",
                    f"medium: {item.get('medium')}" if item.get("medium") else "",
                )
                if part
            )
            detail = f" ({identity})" if identity else ""
            raise StoreError(
                f"El elemento {index + 1}{detail} no contiene campos de asunto y cuerpo reconocibles. "
                f"Asunto admitido: {', '.join(SUBJECT_FIELDS)}. Cuerpo admitido: {', '.join(BODY_FIELDS)}."
            )
    return templates


def make_items(templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "internal_id": f"template-{index + 1}",
            "original": deepcopy(template),
            "result": None,
            "validation": None,
            "actions": [],
            "adaptation_config_signature": None,
            "adaptation_baseline": None,
            "protected_velocity_blocks": [],
            "date_translation": None,
            "publication_preparation": None,
            "publication_backups": [],
            "publication_history": [],
        }
        for index, template in enumerate(templates)
    ]


def _next_item_number(project: dict[str, Any]) -> int:
    return max(
        (int(match.group(1)) for item in project["items"] if (match := re.fullmatch(r"template-(\d+)", item["internal_id"]))),
        default=0,
    ) + 1


def _new_item(template: dict[str, Any], internal_id: str, *, source_filename: str = "", local_copy: bool = False, provenance: dict[str, Any] | None = None) -> dict[str, Any]:
    item = {
        "internal_id": internal_id,
        "original": deepcopy(template),
        "result": None,
        "validation": None,
        "actions": [],
        "adaptation_config_signature": None,
        "adaptation_baseline": None,
        "protected_velocity_blocks": [],
        "date_translation": None,
        "publication_preparation": None,
        "publication_backups": [],
        "publication_history": [],
    }
    if source_filename:
        item["source_filename"] = source_filename
    if local_copy:
        item["local_copy"] = True
    if provenance is not None:
        item["provenance"] = provenance
    return item


def import_local_templates(
    project: dict[str, Any],
    files: list[tuple[str, list[dict[str, Any]]]],
    duplicate_strategy: str,
) -> dict[str, Any]:
    """Append validated local templates while preserving every existing item."""
    existing_by_identity: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for item in project["items"]:
        existing_by_identity.setdefault(template_identity(item["original"]), []).append(item)
    next_number = _next_item_number(project)
    imported_ids: list[str] = []
    skipped = copied = 0
    for filename, templates in files:
        for template in templates:
            identity = template_identity(template)
            duplicate = bool(existing_by_identity.get(identity))
            if duplicate and duplicate_strategy == "skip":
                skipped += 1
                continue
            item = _new_item(
                template,
                f"template-{next_number}",
                source_filename=filename,
                local_copy=duplicate,
            )
            next_number += 1
            project["items"].append(item)
            existing_by_identity.setdefault(identity, []).append(item)
            imported_ids.append(item["internal_id"])
            if duplicate:
                copied += 1
    return {
        "imported": len(imported_ids),
        "skipped": skipped,
        "copied": copied,
        "internal_ids": imported_ids,
    }


def config_signature(config: dict[str, Any]) -> str:
    canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def adaptation_signature(config: dict[str, Any], ai_config: dict[str, Any], style_guide_hash: str = "") -> str:
    return config_signature({"branding": config, "ai": ai_config, "style_guide_hash": style_guide_hash})


def is_config_outdated(item: dict[str, Any], config: dict[str, Any], ai_config: dict[str, Any] | None = None, style_guide_hash: str = "") -> bool:
    expected = adaptation_signature(config, ai_config, style_guide_hash) if ai_config is not None else config_signature(config)
    return bool(item.get("result")) and item.get("adaptation_config_signature") != expected


def summary(item: dict[str, Any], config: dict[str, Any], ai_config: dict[str, Any] | None = None, style_guide_hash: str = "") -> TemplateSummary:
    template = item["original"]
    validation = item.get("validation") or {}
    unsafe_result = any(
        validation.get(field)
        for field in (
            "missing_variables",
            "added_variables",
            "missing_directives",
            "added_directives",
            "directive_order_changed",
            "modified_protected_blocks",
        )
    )
    publication_history = item.get("publication_history") or []
    current_publication_signature = config_signature({"result": item.get("result"), "config": config})

    def publication_applies(record: dict[str, Any]) -> bool:
        signature = record.get("local_signature")
        if isinstance(signature, str) and signature:
            return signature == current_publication_signature
        payload = record.get("payload")
        result = item.get("result")
        if not isinstance(payload, dict) or not isinstance(result, dict):
            return False
        try:
            _, _, result_subject, result_body = editable_content(result)
        except StoreError:
            return False
        return payload.get("subject") == result_subject and payload.get("body") == result_body

    publication_states: list[dict[str, Any]] = []
    seen_connections: set[str] = set()
    for record in reversed(publication_history):
        connection = record.get("connection") if isinstance(record.get("connection"), dict) else {}
        connection_id = str(connection.get("id", ""))
        if not connection_id or connection_id in seen_connections:
            continue
        seen_connections.add(connection_id)
        publication_states.append(
            {
                "publication_id": record.get("publication_id"),
                "status": record.get("status"),
                "connection": connection,
                "message": record.get("message", ""),
                "differences": record.get("differences", []),
                "applies_to_current_result": publication_applies(record),
            }
        )
    return TemplateSummary(
        internal_id=item["internal_id"],
        name=str(template.get("name", template.get("displayName", "Sin nombre"))),
        key=str(template.get("key", "")),
        medium=str(template.get("medium", "")),
        locale=str(template.get("locale", "")),
        has_result=item.get("result") is not None,
        config_outdated=is_config_outdated(item, config, ai_config, style_guide_hash),
        unsafe_result=unsafe_result,
        local_copy=bool(item.get("local_copy")),
        source_filename=str(item.get("source_filename", "")),
        provenance=item.get("provenance"),
        publication_states=publication_states,
    )


def template_identity(template: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(template.get("key", "")).casefold(),
        str(template.get("medium", "")).casefold(),
        str(template.get("locale", "")).casefold(),
    )


def import_isc_templates(
    project: dict[str, Any],
    templates: list[dict[str, Any]],
    provenance: dict[str, Any],
    duplicate_strategy: str,
) -> dict[str, Any]:
    inspect_import(templates)
    existing_by_identity: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for item in project["items"]:
        existing_by_identity.setdefault(template_identity(item["original"]), []).append(item)
    next_number = _next_item_number(project)
    imported_ids: list[str] = []
    skipped = replaced = copied = adaptations_removed = 0
    for template in templates:
        identity = template_identity(template)
        matches = existing_by_identity.get(identity, [])
        existing = next((item for item in matches if not item.get("local_copy")), matches[0] if matches else None)
        source = {**provenance, "read_at": datetime.now(timezone.utc).isoformat()}
        if existing:
            if duplicate_strategy == "skip":
                skipped += 1
                continue
            if duplicate_strategy == "copy":
                item = _new_item(template, f"template-{next_number}", local_copy=True, provenance=source)
                next_number += 1
                project["items"].append(item)
                existing_by_identity[identity].append(item)
                imported_ids.append(item["internal_id"])
                copied += 1
                continue
            if existing.get("result"):
                adaptations_removed += 1
            existing.update(
                original=deepcopy(template),
                result=None,
                validation=None,
                actions=[],
                adaptation_config_signature=None,
                adaptation_baseline=None,
                protected_velocity_blocks=[],
                date_translation=None,
                publication_preparation=None,
                provenance=source,
                local_copy=False,
            )
            imported_ids.append(existing["internal_id"])
            replaced += 1
            continue
        item = _new_item(template, f"template-{next_number}", provenance=source)
        next_number += 1
        project["items"].append(item)
        existing_by_identity.setdefault(identity, []).append(item)
        imported_ids.append(item["internal_id"])
    return {
        "imported": len(imported_ids),
        "skipped": skipped,
        "replaced": replaced,
        "copied": copied,
        "adaptations_removed": adaptations_removed,
        "internal_ids": imported_ids,
    }


def get_item(project: dict[str, Any], internal_id: str) -> dict[str, Any]:
    for item in project["items"]:
        if item["internal_id"] == internal_id:
            return item
    raise StoreError("No se encontró la notificación seleccionada.")


def editable_content(template: dict[str, Any]) -> tuple[str, str, str, str]:
    subject_field = field_name(template, SUBJECT_FIELDS)
    body_field = field_name(template, BODY_FIELDS)
    if not subject_field or not body_field:
        raise StoreError("La plantilla ya no tiene campos editables reconocibles.")
    return subject_field, body_field, template[subject_field], template[body_field]


def _migrate_saved_date_blocks(project: dict[str, Any]) -> bool:
    """Canonicalize only generated blocks in saved adaptations, never originals."""
    variables = list(SUPPORTED_DATE_VARIABLES)
    changed = False
    for item in project.get("items", []):
        baseline = item.get("adaptation_baseline")
        result = item.get("result")
        if not isinstance(baseline, dict) or not isinstance(result, dict):
            continue
        baseline_body = baseline.get("body")
        if not isinstance(baseline_body, str):
            continue

        migrated_baseline = canonicalize_generated_date_blocks(baseline_body, variables)
        old_blocks = [block for block in item.get("protected_velocity_blocks", []) if isinstance(block, str)]
        try:
            subject_field, body_field, result_subject, result_body = editable_content(result)
        except StoreError:
            continue

        migrated_result_body = result_body
        for old_block, new_block in zip(old_blocks, migrated_baseline.protected_blocks):
            if old_block != new_block:
                migrated_result_body = migrated_result_body.replace(old_block, new_block)
        migrated_result = canonicalize_generated_date_blocks(migrated_result_body, variables)
        item_changed = (
            migrated_baseline.body != baseline_body
            or migrated_result.body != result_body
            or old_blocks != list(migrated_baseline.protected_blocks)
        )
        if not item_changed:
            continue

        baseline["body"] = migrated_baseline.body
        result[body_field] = migrated_result.body
        item["protected_velocity_blocks"] = list(migrated_baseline.protected_blocks)
        item["date_translation"] = {
            "applied": True,
            "removable": False,
            "variables": list(migrated_result.transformed_variables),
        }
        baseline_subject = str(baseline.get("subject", result_subject))
        item["validation"] = validate_velocity(
            baseline_subject + "\n" + migrated_baseline.body,
            result_subject + "\n" + migrated_result.body,
            str(project.get("config", {}).get("old_client_name", "")),
            migrated_baseline.protected_blocks,
        ).model_dump()
        item["publication_preparation"] = None
        migration_action = "Bloques de fecha anteriores migrados a la sintaxis compatible con ISC"
        actions = item.setdefault("actions", [])
        if migration_action not in actions:
            actions.append(migration_action)
        changed = True
    return changed

