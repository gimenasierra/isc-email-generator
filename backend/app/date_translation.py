from __future__ import annotations

from dataclasses import dataclass
import re

from .velocity import DIRECTIVE_RE, VARIABLE_RE, extract_velocity


FULL_DATE_NAME_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("Monday", "lunes"),
    ("Tuesday", "martes"),
    ("Wednesday", "miércoles"),
    ("Thursday", "jueves"),
    ("Friday", "viernes"),
    ("Saturday", "sábado"),
    ("Sunday", "domingo"),
    ("January", "enero"),
    ("February", "febrero"),
    ("March", "marzo"),
    ("April", "abril"),
    ("May", "mayo"),
    ("June", "junio"),
    ("July", "julio"),
    ("August", "agosto"),
    ("September", "septiembre"),
    ("October", "octubre"),
    ("November", "noviembre"),
    ("December", "diciembre"),
)

ABBREVIATED_DATE_NAME_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("Mon", "lunes"),
    ("Tue", "martes"),
    ("Wed", "miércoles"),
    ("Thu", "jueves"),
    ("Fri", "viernes"),
    ("Sat", "sábado"),
    ("Sun", "domingo"),
    ("Jan", "enero"),
    ("Feb", "febrero"),
    ("Mar", "marzo"),
    ("Apr", "abril"),
    # May ya está incluido en la lista de nombres completos.
    ("Jun", "junio"),
    ("Jul", "julio"),
    ("Aug", "agosto"),
    ("Sep", "septiembre"),
    ("Oct", "octubre"),
    ("Nov", "noviembre"),
    ("Dec", "diciembre"),
)

DATE_NAME_REPLACEMENTS = FULL_DATE_NAME_REPLACEMENTS + ABBREVIATED_DATE_NAME_REPLACEMENTS

SUPPORTED_DATE_VARIABLES: dict[str, str] = {
    "expires": "fechaExpiracionEs",
    "dateRequested": "fechaSolicitudEs",
    "startDate": "fechaInicioEs",
    "removeDate": "fechaFinEs",
    "detail.startDate": "fechaInicioEs",
    "detail.removeDate": "fechaFinEs",
}

HTML_TAG_RE = re.compile(r"<[^>]*>", re.DOTALL)
NON_VISIBLE_HTML_RE = re.compile(
    r"<!--.*?-->|<script\b[^>]*>.*?</script\s*>|<style\b[^>]*>.*?</style\s*>",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class PreparedDateBody:
    body: str
    protected_blocks: tuple[str, ...]
    transformed_variables: tuple[str, ...]
    replacements: tuple["DateBlockReplacement", ...] = ()


@dataclass(frozen=True)
class DateBlockReplacement:
    variable: str
    source: str
    block: str


def is_spanish(language: str) -> bool:
    normalized = language.strip().casefold()
    return normalized == "es" or "español" in normalized or "espanol" in normalized or "spanish" in normalized


def _reference_name(reference: str) -> str:
    return reference.lstrip("$!{").rstrip("}")


def _protected_spans(text: str, selected: list[str]) -> list[tuple[int, int]]:
    spans = [(match.start(), match.end()) for match in DIRECTIVE_RE.finditer(text)]
    spans.extend((match.start(), match.end()) for match in HTML_TAG_RE.finditer(text))
    spans.extend((match.start(), match.end()) for match in NON_VISIBLE_HTML_RE.finditer(text))
    for match in VARIABLE_RE.finditer(text):
        reference = match.group(0)
        if ("." in reference or "[" in reference or "(" in reference) and _reference_name(reference) not in selected:
            spans.append((match.start(), match.end()))
    return sorted(spans)


def _inside_spans(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < span_end and end > span_start for span_start, span_end in spans)


def _translated_name(text: str, variable: str, reserved: set[str]) -> str:
    base = SUPPORTED_DATE_VARIABLES[variable]
    candidate = base
    suffix = 1
    while candidate in reserved or f"${candidate}" in text or f"${{{candidate}}}" in text:
        candidate = f"{base}_{suffix}"
        suffix += 1
    reserved.add(candidate)
    return candidate


def _translation_expression(
    variable: str,
    braced: bool = False,
    replacements: tuple[tuple[str, str], ...] = DATE_NAME_REPLACEMENTS,
) -> str:
    # ISC acepta llamadas de método sobre `$expires`, pero no sobre `${expires}`.
    expression = f"${{{variable}}}" if braced else f"${variable}"
    for english, spanish in replacements:
        expression += f'.replace("{english}", "{spanish}")'
    return expression


def _block(variable: str, translated_name: str) -> str:
    return f"#set(${translated_name} = {_translation_expression(variable)})${{{translated_name}}}"


def _generated_block_pattern(variable: str) -> re.Pattern[str]:
    translated_base = re.escape(SUPPORTED_DATE_VARIABLES[variable])
    legacy_variable = re.escape(variable.replace(".", "_"))
    target = rf"(?P<target>(?:__iscgen_es_{legacy_variable}(?:_[0-9]+)*|{translated_base}(?:_[0-9]+)?))"
    unbraced = re.escape(_translation_expression(variable))
    legacy_braced = re.escape(_translation_expression(variable, braced=True))
    legacy_full_unbraced = re.escape(
        _translation_expression(variable, replacements=FULL_DATE_NAME_REPLACEMENTS)
    )
    legacy_full_braced = re.escape(
        _translation_expression(variable, braced=True, replacements=FULL_DATE_NAME_REPLACEMENTS)
    )
    return re.compile(
        rf"#set\(\${target}\s*=\s*(?:{unbraced}|{legacy_braced}|{legacy_full_unbraced}|{legacy_full_braced})\)\$\{{(?P=target)\}}"
    )


def _selected_variables(variables: list[str]) -> list[str]:
    return [value for value in dict.fromkeys(variables) if value in SUPPORTED_DATE_VARIABLES]


def canonicalize_generated_date_blocks(body: str, variables: list[str]) -> PreparedDateBody:
    """Migrate only date blocks previously emitted by this application."""
    selected = _selected_variables(variables)
    if not selected:
        return PreparedDateBody(body=body, protected_blocks=(), transformed_variables=())

    reserved = {
        reference.lstrip("$!{").rstrip("}").split(".", 1)[0]
        for reference in extract_velocity(body)[0]
    }
    migrated = body
    transformed: list[str] = []
    for variable in selected:
        pattern = _generated_block_pattern(variable)

        def replace(match: re.Match[str]) -> str:
            target = match.group("target")
            canonical_prefix = SUPPORTED_DATE_VARIABLES[variable]
            if target == canonical_prefix or re.fullmatch(rf"{re.escape(canonical_prefix)}_[0-9]+", target):
                replacement = _block(variable, target)
            else:
                reserved.discard(target)
                replacement = _block(variable, _translated_name(migrated, variable, reserved))
            transformed.append(variable)
            return replacement

        migrated = pattern.sub(replace, migrated)

    found: list[tuple[int, str, str]] = []
    for variable in selected:
        for match in _generated_block_pattern(variable).finditer(migrated):
            found.append((match.start(), match.group(0), variable))
    found.sort(key=lambda item: item[0])
    return PreparedDateBody(
        body=migrated,
        protected_blocks=tuple(block for _, block, _ in found),
        transformed_variables=tuple(dict.fromkeys([*transformed, *(variable for _, _, variable in found)])),
    )


def prepare_spanish_date_body(body: str, variables: list[str], language: str) -> PreparedDateBody:
    """Prepare visible references without interpreting or mutating their date value."""
    selected = _selected_variables(variables)
    if not is_spanish(language) or not selected:
        return PreparedDateBody(body=body, protected_blocks=(), transformed_variables=())

    canonical = canonicalize_generated_date_blocks(body, selected)
    working_body = canonical.body
    generated_spans: list[tuple[int, int]] = []
    for variable in selected:
        generated_spans.extend(
            (match.start(), match.end()) for match in _generated_block_pattern(variable).finditer(working_body)
        )
    protected_spans = [*_protected_spans(working_body, selected), *generated_spans]
    matches: list[tuple[int, int, str]] = []
    for variable in selected:
        pattern = re.compile(
            rf"(?<!\\)(?:\$\{{{re.escape(variable)}\}}(?!\.[A-Za-z_]|\[|\()|\${re.escape(variable)}(?![A-Za-z0-9_]|\.[A-Za-z_]|\[|\())"
        )
        for match in pattern.finditer(working_body):
            if not _inside_spans(match.start(), match.end(), protected_spans):
                matches.append((match.start(), match.end(), variable))

    if not matches:
        return canonical

    matches.sort(key=lambda item: item[0])
    reserved = {
        reference.lstrip("$!{").rstrip("}").split(".", 1)[0]
        for reference in extract_velocity(working_body)[0]
    }
    chunks: list[str] = []
    transformed = list(canonical.transformed_variables)
    replacements: list[DateBlockReplacement] = []
    cursor = 0
    for start, end, variable in matches:
        block = _block(variable, _translated_name(working_body, variable, reserved))
        source = working_body[start:end]
        chunks.extend((working_body[cursor:start], block))
        cursor = end
        transformed.append(variable)
        replacements.append(DateBlockReplacement(variable=variable, source=source, block=block))
    chunks.append(working_body[cursor:])
    prepared_body = "".join(chunks)

    all_blocks: list[tuple[int, str]] = []
    for variable in selected:
        all_blocks.extend(
            (match.start(), match.group(0)) for match in _generated_block_pattern(variable).finditer(prepared_body)
        )
    all_blocks.sort(key=lambda item: item[0])
    return PreparedDateBody(
        body=prepared_body,
        protected_blocks=tuple(block for _, block in all_blocks),
        transformed_variables=tuple(dict.fromkeys(transformed)),
        replacements=tuple(replacements),
    )


def restore_spanish_date_body(body: str, replacements: list[dict[str, str]]) -> str:
    """Remove exact blocks emitted by the postprocessor while preserving surrounding edits."""
    restored = body
    for replacement in replacements:
        block = str(replacement.get("block", ""))
        source = str(replacement.get("source", ""))
        if not block or not source or restored.count(block) != 1:
            raise ValueError("No se puede quitar la traducción porque un bloque de fecha fue modificado o eliminado.")
        restored = restored.replace(block, source, 1)
    return restored
