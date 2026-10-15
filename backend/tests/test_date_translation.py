from __future__ import annotations

import pytest

from app.date_translation import (
    DATE_NAME_REPLACEMENTS,
    canonicalize_generated_date_blocks,
    prepare_spanish_date_body,
)
from app.models import BrandingConfig
from app.providers.base import TemplateContext
from app.providers.remote import adaptation_prompt
from app.velocity import validate_velocity


def replacement_chain(source: str) -> str:
    return source + "".join(
        f'.replace("{english}", "{spanish}")'
        for english, spanish in DATE_NAME_REPLACEMENTS
    )


def test_password_reset_code_uses_unbraced_source_and_descriptive_output() -> None:
    prepared = prepare_spanish_date_body(
        "<p>Este c&oacute;digo expira en cuanto se utilice o el ${expires}.</p>",
        ["expires"],
        "Español neutro",
    )
    expected_block = f"#set($fechaExpiracionEs = {replacement_chain('$expires')})${{fechaExpiracionEs}}"
    assert prepared.body == f"<p>Este c&oacute;digo expira en cuanto se utilice o el {expected_block}.</p>"
    assert prepared.protected_blocks == (expected_block,)
    assert "${expires}.replace" not in prepared.body


def test_translates_all_seven_days_and_twelve_months_without_changing_time() -> None:
    assert len(DATE_NAME_REPLACEMENTS) == 19
    prepared = prepare_spanish_date_body("<p>$expires</p>", ["expires"], "Español neutro")
    block = prepared.protected_blocks[0]
    for english, spanish in DATE_NAME_REPLACEMENTS:
        assert f'.replace("{english}", "{spanish}")' in block

    value = "Thursday 15 October 2026 (18:10:38 GMT)"
    for english, spanish in DATE_NAME_REPLACEMENTS:
        value = value.replace(english, spanish)
    assert value == "jueves 15 octubre 2026 (18:10:38 GMT)"


def test_prepares_only_the_four_validated_variables_inside_original_branches() -> None:
    body = (
        "#if($expires)<p>$expires</p>#end"
        "#if($dateRequested)<p>${dateRequested}</p>#end"
        "#if($startDate)<p>$startDate</p>#end"
        "#if($removeDate)<p>${removeDate}</p>#end"
        "<p>$unvalidatedDate</p>"
    )
    prepared = prepare_spanish_date_body(
        body,
        ["expires", "dateRequested", "startDate", "removeDate", "unvalidatedDate"],
        "Español",
    )
    expected_names = {
        "expires": "fechaExpiracionEs",
        "dateRequested": "fechaSolicitudEs",
        "startDate": "fechaInicioEs",
        "removeDate": "fechaFinEs",
    }
    assert len(prepared.protected_blocks) == 4
    for variable, translated in expected_names.items():
        assert f"#set(${translated} = ${variable}.replace" in prepared.body
        assert body.index(f"#if(${variable})") <= prepared.body.index(f"#set(${translated}")
    assert "$unvalidatedDate" in prepared.body


def test_skips_attributes_nested_references_directives_and_existing_calls() -> None:
    body = (
        '#if($expires)<a title="$expires" href="$expires">Visible $expires.</a>#end '
        "$detail.removeDate $expires.replace('Thursday','jueves') ${expires}.replace('Thursday','jueves') "
        "$spTools.formatDate($expires, 'yyyy') <script>const value = '$expires'</script>"
    )
    prepared = prepare_spanish_date_body(body, ["expires", "removeDate"], "es")
    assert len(prepared.protected_blocks) == 1
    assert '#if($expires)' in prepared.body
    assert 'title="$expires"' in prepared.body
    assert 'href="$expires"' in prepared.body
    assert "$detail.removeDate" in prepared.body
    assert "$expires.replace('Thursday','jueves')" in prepared.body
    assert "${expires}.replace('Thursday','jueves')" in prepared.body
    assert "$spTools.formatDate($expires, 'yyyy')" in prepared.body
    assert "const value = '$expires'" in prepared.body


def test_uses_safe_suffix_when_descriptive_name_already_exists() -> None:
    body = "$fechaExpiracionEs <p>$expires</p>"
    prepared = prepare_spanish_date_body(body, ["expires"], "Spanish")
    assert "#set($fechaExpiracionEs_1 = $expires.replace" in prepared.body
    assert "${fechaExpiracionEs_1}" in prepared.body


def test_migrates_legacy_braced_block_and_is_idempotent() -> None:
    legacy_name = "__iscgen_es_expires_1"
    legacy = f"#set(${legacy_name} = {replacement_chain('${expires}')})${{{legacy_name}}}"
    body = f"<p>{legacy}</p>"
    first = prepare_spanish_date_body(body, ["expires"], "Español")
    second = prepare_spanish_date_body(first.body, ["expires"], "Español")
    assert "#set($fechaExpiracionEs = $expires.replace" in first.body
    assert "${expires}.replace" not in first.body
    assert legacy_name not in first.body
    assert second.body == first.body
    assert second.protected_blocks == first.protected_blocks
    assert second.body.count("#set($fechaExpiracionEs = ") == 1


def test_canonicalizer_does_not_transform_raw_references_or_unrelated_sets() -> None:
    custom = '#set($fecha = $expires.replace("Thursday", "jueves"))'
    body = f"<p>$expires</p>{custom}"
    migrated = canonicalize_generated_date_blocks(body, ["expires"])
    assert migrated.body == body
    assert migrated.protected_blocks == ()


def test_non_spanish_language_does_not_prepare_dates() -> None:
    body = "<p>$expires</p>"
    prepared = prepare_spanish_date_body(body, ["expires"], "English")
    assert prepared.body == body
    assert prepared.protected_blocks == ()


def test_prompt_contains_exact_protected_block_and_explains_source_and_output() -> None:
    prepared = prepare_spanish_date_body("<p>$expires</p>", ["expires"], "Español")
    prompt = adaptation_prompt(
        "Aviso",
        prepared.body,
        BrandingConfig(target_language="Español"),
        TemplateContext("Aviso", "key", "en", protected_velocity_blocks=prepared.protected_blocks),
    )
    assert "CUERPO BASE PREPARADO POR LA APLICACIÓN" in prompt
    assert prepared.protected_blocks[0] in prompt
    assert "protected_velocity_blocks_verbatim" in prompt
    assert "referencia original sin llaves" in prompt
    assert "variable descriptiva entre llaves" in prompt


def test_validation_rejects_a_modified_or_missing_protected_block() -> None:
    prepared = prepare_spanish_date_body("<p>$expires</p>", ["expires"], "Español")
    exact = validate_velocity(prepared.body, prepared.body, protected_blocks=prepared.protected_blocks)
    assert exact.modified_protected_blocks == []

    changed_body = prepared.body.replace('.replace("October", "octubre")', "")
    changed = validate_velocity(prepared.body, changed_body, protected_blocks=prepared.protected_blocks)
    assert changed.modified_protected_blocks == ["Bloque de traducción determinista 1"]
    assert changed.suspicious is True


def test_date_variable_configuration_accepts_only_validated_names() -> None:
    config = BrandingConfig(spanish_date_variables=["expires", "expires", "startDate"])
    assert config.spanish_date_variables == ["expires", "startDate"]

    for invalid in ("$expires", "detail.removeDate", "customDate", "expires.replace()"):
        with pytest.raises(ValueError):
            BrandingConfig(spanish_date_variables=[invalid])
