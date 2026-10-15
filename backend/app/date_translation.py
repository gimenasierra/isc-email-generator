from __future__ import annotations

from dataclasses import dataclass
import re

from .velocity import DIRECTIVE_RE, VARIABLE_RE, extract_velocity


DATE_NAME_REPLACEMENTS: tuple[tuple[str, str], ...] = (
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

SUPPORTED_DATE_VARIABLES: dict[str, str] = {
    "expires": "fechaExpiracionEs",
    "dateRequested": "fechaSolicitudEs",
    "startDate": "fechaInicioEs",
    "removeDate": "fechaFinEs",
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


def is_spanish(language: str) -> bool:
    normalized = language.strip().casefold()
    return normalized == "es" or "español" in normalized or "espanol" in normalized or "spanish" in normalized


def _protected_spans(text: str) -> list[tuple[int, int]]:
    spans = [(match.start(), match.end()) for match in DIRECTIVE_RE.finditer(text)]
    spans.extend((match.start(), match.end()) for match in HTML_TAG_RE.finditer(text))
    spans.extend((match.start(), match.end()) for match in NON_VISIBLE_HTML_RE.finditer(text))
    for match in VARIABLE_RE.finditer(text):
        reference = match.group(0)
        if "." in reference or "[" in reference or "(" in reference:
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


def _translation_expression(variable: str, braced: bool = False) -> str:
    # ISC acepta llamadas de método sobre `$expires`, pero no sobre `${expires}`.
    expression = f"${{{variable}}}" if braced else f"${variable}"
    for english, spanish in DATE_NAME_REPLACEMENTS:
        expression += f'.replace("{english}", "{spanish}")'
    return expression


def _block(variable: str, translated_name: str) -> str:
    return f"#set(${translated_name} = {_translation_expression(variable)})${{{translated_name}}}"


def _generated_block_pattern(variable: str) -> re.Pattern[str]:
    translated_base = re.escape(SUPPORTED_DATE_VARIABLES[variable])
    target = rf"(?P<target>(?:__iscgen_es_{re.escape(variable)}(?:_[0-9]+)*|{translated_base}(?:_[0-9]+)?))"
    unbraced = re.escape(_translation_expression(variable))
    legacy_braced = re.escape(_translation_expression(variable, braced=True))
    return re.compile(
        rf"#set\(\${target}\s*=\s*(?:{unbraced}|{legacy_braced})\)\$\{{(?P=target)\}}"
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
    protected_spans = [*_protected_spans(working_body), *generated_spans]
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
    cursor = 0
    for start, end, variable in matches:
        block = _block(variable, _translated_name(working_body, variable, reserved))
        chunks.extend((working_body[cursor:start], block))
        cursor = end
        transformed.append(variable)
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
    )
