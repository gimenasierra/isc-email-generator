from __future__ import annotations

from ..models import BrandingConfig, MappingEntry
from ..velocity import DIRECTIVE_RE, VARIABLE_RE
from .base import AdaptationProvider, AdaptationResult, ConnectionResult, TemplateContext
from ..models import AIConfig


class MockAdaptationProvider(AdaptationProvider):
    name = "Simulado — reemplazos explícitos"
    is_simulated = True

    def _replace_outside_velocity(self, text: str, source: str, target: str) -> str:
        if not source or not target or source == target:
            return text
        matches = sorted(
            [*VARIABLE_RE.finditer(text), *DIRECTIVE_RE.finditer(text)],
            key=lambda match: match.start(),
        )
        parts: list[str] = []
        cursor = 0
        for match in matches:
            if match.start() < cursor:
                continue
            parts.append(text[cursor : match.start()].replace(source, target))
            parts.append(match.group(0))
            cursor = match.end()
        parts.append(text[cursor:].replace(source, target))
        return "".join(parts)

    def _valid_pairs(self, entries: list[MappingEntry]) -> list[tuple[str, str]]:
        return [(entry.source, entry.target) for entry in entries if entry.source and entry.target]

    def adapt(self, subject: str, body: str, config: BrandingConfig, settings: AIConfig, api_key: str, context: TemplateContext) -> AdaptationResult:
        pairs: list[tuple[str, str, str]] = []
        if config.old_client_name and config.new_client_name:
            pairs.append((config.old_client_name, config.new_client_name, "nombre del cliente"))
        if config.old_logo_url and config.new_logo_url:
            pairs.append((config.old_logo_url, config.new_logo_url, "URL del logo"))
        pairs.extend((source, target, "color") for source, target in self._valid_pairs(config.color_mappings))
        pairs.extend((source, target, "correo") for source, target in self._valid_pairs(config.email_mappings))
        pairs.extend((source, target, "URL") for source, target in self._valid_pairs(config.url_mappings))

        result_subject, result_body = subject, body
        actions: list[str] = []
        for source, target, label in pairs:
            new_subject = self._replace_outside_velocity(result_subject, source, target)
            new_body = self._replace_outside_velocity(result_body, source, target)
            if (new_subject, new_body) != (result_subject, result_body):
                actions.append(f"Reemplazo de {label}: {source} → {target}")
            result_subject, result_body = new_subject, new_body

        ignored = []
        if any([config.product_display_name, config.greeting, config.treatment, config.signature]):
            ignored.append("Los campos editoriales se guardaron pero el proveedor simulado no decide dónde insertarlos.")
        if config.color_instructions:
            ignored.append("Las indicaciones de color se guardaron pero el proveedor simulado solo aplica pares exactos.")
        if config.additional_instructions:
            ignored.append("Las instrucciones adicionales se guardaron pero no son interpretadas por el proveedor simulado.")
        if config.target_language or config.generate_missing_title:
            ignored.append("El idioma de destino y la generación de títulos requieren un proveedor con IA.")
        if config.mode == "guide":
            ignored.append("La guía de estilo se conserva pero el proveedor simulado no rediseña la plantilla.")
        actions.extend(ignored)
        if not actions:
            actions.append("No se encontraron reemplazos explícitos aplicables; el contenido se conservó sin cambios.")
        return AdaptationResult(result_subject, result_body, actions)

    def test_connection(self, settings: AIConfig, api_key: str) -> ConnectionResult:
        return ConnectionResult("Proveedor simulado listo. No realiza solicitudes externas ni consume cuota.")

