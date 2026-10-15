from __future__ import annotations

import re
from collections import Counter

from .models import ValidationReport


VARIABLE_RE = re.compile(
    r"(?<!\\)\$(?:!\{[^}\r\n]+\}|\{[^}\r\n]+\}|!?[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*(?:\([^\r\n)]*\))?|\[[^\r\n\]]+\])*)"
)
DIRECTIVE_RE = re.compile(
    r"(?<!#)#\{(?:if|elseif|foreach|set|macro|parse|include|evaluate|define|stop)\}\s*"
    r"\((?:[^()'\"\r\n]+|'[^'\r\n]*'|\"[^\"\r\n]*\"|\([^()\r\n]*\))*\)"
    r"|(?<!#)#\{(?:else|end|break|continue)\}"
    r"|(?<!#)#(?:if|elseif|foreach|set|macro|parse|include|evaluate|define|stop)\s*"
    r"\((?:[^()'\"\r\n]+|'[^'\r\n]*'|\"[^\"\r\n]*\"|\([^()\r\n]*\))*\)"
    r"|(?<!#)#(?:else|end|break|continue)\b",
    re.IGNORECASE,
)


def extract_velocity(text: str) -> tuple[list[str], list[str]]:
    return VARIABLE_RE.findall(text), DIRECTIVE_RE.findall(text)


def _counter_diff(left: list[str], right: list[str]) -> list[str]:
    difference = Counter(left) - Counter(right)
    return sorted(item for item, count in difference.items() for _ in range(count))


def validate_velocity(
    original: str,
    result: str,
    old_client_name: str = "",
    protected_blocks: list[str] | tuple[str, ...] | None = None,
) -> ValidationReport:
    original_variables, original_directives = extract_velocity(original)
    result_variables, result_directives = extract_velocity(result)
    pending: list[str] = []
    if old_client_name:
        for line_number, line in enumerate(result.splitlines(), start=1):
            if old_client_name.casefold() in line.casefold():
                pending.append(f"Línea {line_number}: {line.strip()[:180]}")

    missing_variables = _counter_diff(original_variables, result_variables)
    extra_variables = _counter_diff(result_variables, original_variables)
    original_variable_names = set(original_variables)
    added_variables = [value for value in extra_variables if value not in original_variable_names]
    repeated_variables = [value for value in extra_variables if value in original_variable_names]
    missing_directives = _counter_diff(original_directives, result_directives)
    added_directives = _counter_diff(result_directives, original_directives)
    directive_order_changed = not missing_directives and not added_directives and original_directives != result_directives
    modified_protected_blocks = [
        f"Bloque de traducción determinista {index}"
        for index, block in enumerate(protected_blocks or (), start=1)
        if block not in result
    ]
    return ValidationReport(
        original_variables=original_variables,
        result_variables=result_variables,
        missing_variables=missing_variables,
        added_variables=added_variables,
        repeated_variables=repeated_variables,
        original_directives=original_directives,
        result_directives=result_directives,
        missing_directives=missing_directives,
        added_directives=added_directives,
        directive_order_changed=directive_order_changed,
        modified_protected_blocks=modified_protected_blocks,
        pending_old_client_references=pending,
        suspicious=bool(
            missing_variables
            or added_variables
            or repeated_variables
            or missing_directives
            or added_directives
            or directive_order_changed
            or modified_protected_blocks
            or pending
        ),
    )

