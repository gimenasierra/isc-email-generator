from __future__ import annotations

from app.date_translation import (
    ABBREVIATED_DATE_NAME_REPLACEMENTS,
    DATE_NAME_REPLACEMENTS,
    FULL_DATE_NAME_REPLACEMENTS,
    canonicalize_generated_date_blocks,
    prepare_spanish_date_body,
    restore_spanish_date_body,
)
from app.models import BrandingConfig
from app.providers.base import TemplateContext
from app.providers.remote import adaptation_prompt
from app.velocity import validate_velocity


def replacement_chain(source: str, replacements=DATE_NAME_REPLACEMENTS) -> str:
    return source + "".join(
        f'.replace("{english}", "{spanish}")'
        for english, spanish in replacements
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


def test_translates_full_and_abbreviated_date_names_without_changing_time() -> None:
    assert len(FULL_DATE_NAME_REPLACEMENTS) == 19
    assert len(ABBREVIATED_DATE_NAME_REPLACEMENTS) == 18
    prepared = prepare_spanish_date_body("<p>$expires</p>", ["expires"], "Español neutro")
    block = prepared.protected_blocks[0]
    for english, spanish in DATE_NAME_REPLACEMENTS:
        assert f'.replace("{english}", "{spanish}")' in block

    value = "Thursday 15 October 2026 (18:10:38 GMT)"
    for english, spanish in DATE_NAME_REPLACEMENTS:
        value = value.replace(english, spanish)
    assert value == "jueves 15 octubre 2026 (18:10:38 GMT)"

    abbreviated = "Fri Oct 23 03:00:00 UTC 2026"
    for english, spanish in DATE_NAME_REPLACEMENTS:
        abbreviated = abbreviated.replace(english, spanish)
    assert abbreviated == "viernes octubre 23 03:00:00 UTC 2026"


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


def test_translates_only_the_validated_detail_dates_inside_their_branches() -> None:
    body = (
        "#foreach($detail in $requestedObjectDetailsByType.get($type))"
        "<p>$detail.name "
        "#if($detail.startDate)Start: ${detail.startDate}#end "
        "#if($detail.removeDate)End: ${detail.removeDate}#end"
        "</p>#end"
    )
    prepared = prepare_spanish_date_body(
        body,
        ["detail.startDate", "detail.removeDate"],
        "Español",
    )
    assert "#if($detail.startDate)Start: #set($fechaInicioEs = $detail.startDate.replace" in prepared.body
    assert "#if($detail.removeDate)End: #set($fechaFinEs = $detail.removeDate.replace" in prepared.body
    assert "${fechaInicioEs}#end" in prepared.body
    assert "${fechaFinEs}#end" in prepared.body
    assert "$detail.name" in prepared.body
    assert len(prepared.protected_blocks) == 2


def test_uses_safe_suffix_when_descriptive_name_already_exists() -> None:
    body = "$fechaExpiracionEs <p>$expires</p>"
    prepared = prepare_spanish_date_body(body, ["expires"], "Spanish")
    assert "#set($fechaExpiracionEs_1 = $expires.replace" in prepared.body
    assert "${fechaExpiracionEs_1}" in prepared.body


def test_migrates_legacy_braced_block_and_is_idempotent() -> None:
    legacy_name = "__iscgen_es_expires_1"
    legacy = f"#set(${legacy_name} = {replacement_chain('${expires}', FULL_DATE_NAME_REPLACEMENTS)})${{{legacy_name}}}"
    body = f"<p>{legacy}</p>"
    first = prepare_spanish_date_body(body, ["expires"], "Español")
    second = prepare_spanish_date_body(first.body, ["expires"], "Español")
    assert "#set($fechaExpiracionEs = $expires.replace" in first.body
    assert "${expires}.replace" not in first.body
    assert legacy_name not in first.body
    assert second.body == first.body
    assert second.protected_blocks == first.protected_blocks
    assert second.body.count("#set($fechaExpiracionEs = ") == 1


def test_migrates_existing_nested_date_block_to_include_abbreviations() -> None:
    legacy = (
        "#set($fechaFinEs = "
        + replacement_chain("$detail.removeDate", FULL_DATE_NAME_REPLACEMENTS)
        + ")${fechaFinEs}"
    )
    prepared = prepare_spanish_date_body(
        f"#if($detail.removeDate)<p>{legacy}</p>#end",
        ["detail.removeDate"],
        "Español",
    )
    assert prepared.body.count("#set($fechaFinEs = ") == 1
    assert '.replace("Fri", "viernes")' in prepared.body
    assert '.replace("Oct", "octubre")' in prepared.body


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


def test_records_exact_replacements_and_restores_original_notation() -> None:
    original = "<p>Expira: ${expires}</p>"
    prepared = prepare_spanish_date_body(original, ["expires"], "Español")
    assert prepared.replacements[0].source == "${expires}"
    assert prepared.replacements[0].block == prepared.protected_blocks[0]
    restored = restore_spanish_date_body(
        prepared.body,
        [replacement.__dict__ for replacement in prepared.replacements],
    )
    assert restored == original


def test_ai_prompt_receives_the_original_date_reference_without_postprocessing() -> None:
    prompt = adaptation_prompt(
        "Aviso",
        "<p>Expires: $expires</p>",
        BrandingConfig(target_language="Español"),
        TemplateContext("Aviso", "key", "en"),
    )
    assert "<p>Expires: $expires</p>" in prompt
    assert "fechaExpiracionEs" not in prompt


def test_validation_rejects_a_modified_or_missing_protected_block() -> None:
    prepared = prepare_spanish_date_body("<p>$expires</p>", ["expires"], "Español")
    exact = validate_velocity(prepared.body, prepared.body, protected_blocks=prepared.protected_blocks)
    assert exact.modified_protected_blocks == []

    changed_body = prepared.body.replace('.replace("October", "octubre")', "")
    changed = validate_velocity(prepared.body, changed_body, protected_blocks=prepared.protected_blocks)
    assert changed.modified_protected_blocks == ["Bloque de traducción determinista 1"]
    assert changed.suspicious is True
