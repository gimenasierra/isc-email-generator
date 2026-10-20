from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import BACKEND_DIR, state_path
from .velocity import DIRECTIVE_RE, VARIABLE_RE


PROMPTS_DIR = BACKEND_DIR / "prompts"
BASE_RULES_FILE = PROMPTS_DIR / "adaptation_rules.md"
PROJECT_RULES_DIR = state_path("prompts", "projects", development_default=PROMPTS_DIR / "projects")
MAX_GUIDE_BYTES = 100_000
URL_RE = re.compile(r"(?i)(?:https?://|mailto:)[^\s<>\"')\]]+")
ENVIRONMENT_RE = re.compile(r"(?i)\b(?:sandbox|producci[oó]n|production|demo|tenant|identitynow|identitynow-demo)\b")


class PromptRulesError(RuntimeError):
    pass


def _safe_project_id(project_id: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]", "-", project_id).strip("-")[:80]
    return value or "default"


def _guide_paths(project_id: str) -> tuple[Path, Path]:
    safe_id = _safe_project_id(project_id)
    return PROJECT_RULES_DIR / f"{safe_id}.md", PROJECT_RULES_DIR / f"{safe_id}.meta.json"


def load_adaptation_rules() -> tuple[str, Path]:
    try:
        rules = BASE_RULES_FILE.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise PromptRulesError(f"No se pudieron leer las reglas técnicas de IA: {BASE_RULES_FILE}") from exc
    if not rules:
        raise PromptRulesError(f"El contrato técnico de IA está vacío: {BASE_RULES_FILE}")
    if len(rules.encode("utf-8")) > MAX_GUIDE_BYTES:
        raise PromptRulesError(f"El contrato técnico de IA supera el límite de 100 KB: {BASE_RULES_FILE}")
    return rules, BASE_RULES_FILE


def style_guide_warnings(content: str) -> list[str]:
    warnings: list[str] = []
    variable_count = len(VARIABLE_RE.findall(content))
    directive_count = len(DIRECTIVE_RE.findall(content))
    url_count = len(URL_RE.findall(content))
    environments = sorted({match.group(0) for match in ENVIRONMENT_RE.finditer(content)}, key=str.casefold)
    if variable_count:
        warnings.append(f"Se detectaron {variable_count} variable(s) Velocity de ejemplo. Se neutralizarán antes de enviar la guía a la IA.")
    if directive_count:
        warnings.append(f"Se detectaron {directive_count} directiva(s) Velocity de ejemplo. Se neutralizarán antes de enviar la guía a la IA.")
    if url_count:
        warnings.append(f"Se detectaron {url_count} URL(s) o correo(s). Se retirarán de la guía enviada a la IA.")
    if environments:
        warnings.append("La guía menciona ambientes o tenants que conviene revisar: " + ", ".join(environments[:8]) + ".")
    return warnings


def sanitize_style_guide(content: str) -> str:
    """Preserve design rules while preventing example data from becoming authorized content."""
    sanitized = re.sub(r"<script\b[^>]*>.*?</script\s*>", "", content, flags=re.IGNORECASE | re.DOTALL)
    sanitized = DIRECTIVE_RE.sub("[DIRECTIVA_VELOCITY_DE_EJEMPLO_NEUTRALIZADA]", sanitized)
    sanitized = VARIABLE_RE.sub("[VARIABLE_VELOCITY_DE_EJEMPLO_NEUTRALIZADA]", sanitized)
    sanitized = URL_RE.sub("[URL_DE_EJEMPLO_RETIRADA]", sanitized)
    return sanitized.strip()


def _metadata(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def get_style_guide(project_id: str) -> dict[str, Any]:
    guide_path, metadata_path = _guide_paths(project_id)
    if not guide_path.is_file():
        return {"configured": False, "content": "", "filename": "", "updated_at": None, "hash": "", "warnings": []}
    try:
        content = guide_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PromptRulesError("No se pudo leer la guía de estilo UTF-8 del proyecto.") from exc
    metadata = _metadata(metadata_path)
    return {
        "configured": True,
        "content": content,
        "filename": str(metadata.get("filename") or guide_path.name),
        "updated_at": metadata.get("updated_at") or datetime.fromtimestamp(guide_path.stat().st_mtime, timezone.utc).isoformat(),
        "hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "warnings": style_guide_warnings(content),
    }


def save_style_guide(project_id: str, content: str, filename: str = "") -> dict[str, Any]:
    encoded = content.encode("utf-8")
    if not content.strip():
        raise PromptRulesError("La guía Markdown está vacía.")
    if len(encoded) > MAX_GUIDE_BYTES:
        raise PromptRulesError("La guía Markdown supera el límite de 100 KB.")
    clean_filename = Path(filename.strip()).name if filename.strip() else "guia-estilo.md"
    if Path(clean_filename).suffix.casefold() not in {".md", ".markdown"}:
        raise PromptRulesError("La guía debe ser un archivo Markdown (.md o .markdown).")
    guide_path, metadata_path = _guide_paths(project_id)
    PROJECT_RULES_DIR.mkdir(parents=True, exist_ok=True)
    updated_at = datetime.now(timezone.utc).isoformat()
    guide_tmp = guide_path.with_suffix(".md.tmp")
    metadata_tmp = metadata_path.with_suffix(".json.tmp")
    guide_tmp.write_text(content, encoding="utf-8")
    metadata_tmp.write_text(json.dumps({"filename": clean_filename, "updated_at": updated_at}, ensure_ascii=False, indent=2), encoding="utf-8")
    guide_tmp.replace(guide_path)
    metadata_tmp.replace(metadata_path)
    return get_style_guide(project_id)


def delete_style_guide(project_id: str) -> dict[str, Any]:
    guide_path, metadata_path = _guide_paths(project_id)
    guide_path.unlink(missing_ok=True)
    metadata_path.unlink(missing_ok=True)
    return get_style_guide(project_id)
