from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app.date_translation import DATE_NAME_REPLACEMENTS
from app.main import adapt_template, clear_templates, create_isc_connection, delete_isc_connection, delete_project_style_guide, delete_template, download_result, edit_result, get_project, get_project_style_guide, get_template, import_templates, put_ai_config, put_config, put_project_style_guide, safe_download_filename
from app.models import AIConfigUpdate, AdaptRequest, BrandingConfig, EditResultRequest, ImportRequest, ISCConnectionInput, StyleGuideUpdate
from app.providers.base import AdaptationResult
from app.store import StoreError


SAMPLE = {
    "id": "immutable-42",
    "name": "Alta de cuenta",
    "key": "cloud_account_created",
    "medium": "EMAIL",
    "locale": "es",
    "subject": "Bienvenido a Cliente Viejo, $displayName",
    "body": """<p>#if($manager)Hola ${displayName}#else Hola#end</p>
<img src=\"https://old.example/logo.png\">
<a href=\"https://old.example/access?token=$token\">Ingresar</a>
<p style=\"color:#112233\">Cliente Viejo</p>""",
    "unrelatedMetadata": {"keep": True},
}


def test_download_filename_is_safe_for_untrusted_template_keys():
    assert safe_download_filename('bad"\r\nX-Evil: yes', 'fallback') == "bad-X-Evil-yes"
    assert safe_download_filename("áé / \\ ?", "fallback") == "fallback"
    assert len(safe_download_filename("a" * 300, "fallback")) == 120


def test_import_adapt_edit_download(tmp_path, monkeypatch):
    from app import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    project = "test-flow"
    imported = import_templates(project, ImportRequest(filename="sample.json", data=[SAMPLE]))
    internal_id = imported["templates"][0]["internal_id"]

    config = {
        "old_client_name": "Cliente Viejo",
        "new_client_name": "Cliente Nuevo",
        "old_logo_url": "https://old.example/logo.png",
        "new_logo_url": "https://new.example/logo.png",
        "color_mappings": [{"source": "#112233", "target": "#445566"}],
        "url_mappings": [{"source": "https://old.example/access", "target": "https://new.example/access"}],
    }
    put_config(project, BrandingConfig.model_validate(config))
    payload = adapt_template(project, AdaptRequest(internal_id=internal_id))
    assert "Cliente Nuevo" in payload["result_subject"]
    assert "$displayName" in payload["result_subject"]
    assert "#if($manager)" in payload["result_body"]
    assert "?token=$token" in payload["result_body"]
    assert "https://new.example/access?token=$token" in payload["result_body"]
    assert payload["validation"]["missing_variables"] == []
    assert payload["validation"]["missing_directives"] == []
    assert payload["config_outdated"] is False

    changed_config = BrandingConfig.model_validate({**config, "new_client_name": "Otro Cliente"})
    put_config(project, changed_config)
    assert get_project(project)["templates"][0]["config_outdated"] is True
    assert adapt_template(project, AdaptRequest(internal_id=internal_id))["config_outdated"] is False

    edited_body = payload["result_body"].replace("${displayName}", "texto fijo")
    edited = edit_result(
        project,
        internal_id,
        EditResultRequest(subject=payload["result_subject"], body=edited_body),
    )
    assert edited["validation"]["suspicious"] is True
    assert "${displayName}" in edited["validation"]["missing_variables"]
    assert get_project(project)["templates"][0]["unsafe_result"] is True

    with pytest.raises(HTTPException, match="descarga está bloqueada") as blocked:
        download_result(project, internal_id)
    assert blocked.value.status_code == 409

    repaired = edit_result(
        project,
        internal_id,
        EditResultRequest(subject=payload["result_subject"], body=payload["result_body"]),
    )
    assert repaired["validation"]["suspicious"] is False
    assert get_project(project)["templates"][0]["unsafe_result"] is False
    downloaded = download_result(project, internal_id)
    result = json.loads(downloaded.body)
    assert result["id"] == SAMPLE["id"]
    assert result["key"] == SAMPLE["key"]
    assert result["unrelatedMetadata"] == {"keep": True}
    assert result["body"] == payload["result_body"]


def test_visual_edit_rejects_velocity_changes_without_saving(tmp_path, monkeypatch):
    from app import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    project = "visual-edit"
    imported = import_templates(project, ImportRequest(filename="sample.json", data=[SAMPLE]))
    internal_id = imported["templates"][0]["internal_id"]
    adapted = adapt_template(project, AdaptRequest(internal_id=internal_id))

    saved = store.load_project(project)
    saved["items"][0]["publication_preparation"] = {"preparation_id": "keep-on-rejection"}
    store.save_project(project, saved)
    damaged = adapted["result_body"].replace("${displayName}", "Nombre")

    with pytest.raises(HTTPException, match="edición visual alteró") as rejected:
        edit_result(
            project,
            internal_id,
            EditResultRequest(
                subject=adapted["result_subject"],
                body=damaged,
                editor_mode="visual",
            ),
        )
    assert rejected.value.status_code == 409
    unchanged = get_template(project, internal_id)
    assert unchanged["result_body"] == adapted["result_body"]
    assert unchanged["publication_preparation"] == {"preparation_id": "keep-on-rejection"}

    formatted = adapted["result_body"].replace("Cliente Viejo", '<strong style="color:#0079c1">Cliente Viejo</strong>')
    accepted = edit_result(
        project,
        internal_id,
        EditResultRequest(
            subject=adapted["result_subject"],
            body=formatted,
            editor_mode="visual",
        ),
    )
    assert accepted["result_body"] == formatted
    assert accepted["publication_preparation"] is None


def test_rejects_truncated_ai_result_before_saving(tmp_path, monkeypatch):
    from app import main, store

    class BrokenProvider:
        name = "Proveedor roto"
        is_simulated = False

        def adapt(self, subject, body, config, settings, api_key, context):
            return AdaptationResult(subject, "<p>Su名称为", ["Cambio incompleto"])

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "provider_for", lambda _: BrokenProvider())
    project = "unsafe-ai"
    imported = import_templates(project, ImportRequest(filename="sample.json", data=[SAMPLE]))
    internal_id = imported["templates"][0]["internal_id"]

    with pytest.raises(HTTPException, match="adaptación insegura") as rejected:
        adapt_template(project, AdaptRequest(internal_id=internal_id))
    assert rejected.value.status_code == 502
    assert get_template(project, internal_id)["result"] is None


def test_date_baseline_is_stored_and_modified_block_blocks_download(tmp_path, monkeypatch):
    from app import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    project = "date-baseline"
    template = {
        **SAMPLE,
        "key": "date_notice",
        "subject": "Date notice",
        "body": "#if($expires)<p>Expires: $expires</p>#end",
    }
    imported = import_templates(project, ImportRequest(filename="date.json", data=template))
    internal_id = imported["templates"][0]["internal_id"]
    put_config(project, BrandingConfig(target_language="Español", spanish_date_variables=["expires"]))

    adapted = adapt_template(project, AdaptRequest(internal_id=internal_id))
    assert ".replace(\"Thursday\", \"jueves\")" in adapted["result_body"]
    saved_item = store.load_project(project)["items"][0]
    assert saved_item["adaptation_baseline"]["body"] == adapted["result_body"]
    assert len(saved_item["protected_velocity_blocks"]) == 1

    damaged = adapted["result_body"].replace('.replace("October", "octubre")', "")
    edited = edit_result(
        project,
        internal_id,
        EditResultRequest(subject=adapted["result_subject"], body=damaged),
    )
    assert edited["validation"]["modified_protected_blocks"] == ["Bloque de traducción determinista 1"]
    with pytest.raises(HTTPException, match="descarga está bloqueada"):
        download_result(project, internal_id)


def test_load_migrates_saved_legacy_date_blocks_without_touching_original(tmp_path, monkeypatch):
    from app import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    source = "${expires}" + "".join(
        f'.replace("{english}", "{spanish}")'
        for english, spanish in DATE_NAME_REPLACEMENTS
    )
    legacy = f"#set($__iscgen_es_expires_1 = {source})${{__iscgen_es_expires_1}}"
    original_body = "<p>Expires: ${expires}</p>"
    adapted_body = f"<p>Expira: {legacy}</p>"
    project = {
        "project_id": "legacy-date",
        "filename": "legacy.json",
        "config": BrandingConfig(target_language="Español").model_dump(),
        "ai_config": {"provider": "simulated", "model": "", "base_url": ""},
        "isc_connections": [],
        "items": [{
            "internal_id": "template-1",
            "original": {**SAMPLE, "body": original_body},
            "result": {**SAMPLE, "body": adapted_body},
            "validation": None,
            "actions": [],
            "adaptation_config_signature": "legacy",
            "adaptation_baseline": {"subject": SAMPLE["subject"], "body": adapted_body},
            "protected_velocity_blocks": [legacy],
            "publication_preparation": {"preparation_id": "must-be-invalidated"},
            "publication_backups": [],
            "publication_history": [],
        }],
    }
    path = tmp_path / "legacy-date.json"
    path.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")

    loaded = store.load_project("legacy-date")
    item = loaded["items"][0]
    assert item["original"]["body"] == original_body
    assert "#set($fechaExpiracionEs = $expires.replace" in item["result"]["body"]
    assert "${expires}.replace" not in item["result"]["body"]
    assert item["adaptation_baseline"]["body"] == item["result"]["body"]
    assert item["protected_velocity_blocks"] == [
        item["result"]["body"].removeprefix("<p>Expira: ").removesuffix("</p>")
    ]
    assert item["publication_preparation"] is None
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["items"][0]["result"]["body"] == item["result"]["body"]


def test_rejects_unrecognized_structure(tmp_path, monkeypatch):
    from app import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    try:
        import_templates("bad", ImportRequest(filename="bad.json", data={"notifications": [SAMPLE]}))
    except StoreError as exc:
        assert "campos de asunto y cuerpo" in str(exc)
    else:
        raise AssertionError("La estructura no reconocida debería rechazarse")


def test_isc_candidate_list_filters_non_email_media_locally(monkeypatch):
    from app import main

    connection = {
        "id": "connection-1",
        "name": "Tenant",
        "environment": "sandbox",
        "api_base_url": "https://tenant.api.identitynow.com",
    }
    project = {"isc_connections": [connection]}
    email = {**SAMPLE, "name": "Email", "key": "email-key"}
    slack = {
        "name": "Access Request with ROBO",
        "key": "access_request_with_robo",
        "medium": "SLACK",
        "locale": "en",
        "subject": None,
        "body": "{}",
    }
    teams = {**slack, "name": "Teams", "medium": "TEAMS"}
    monkeypatch.setattr(main, "load_project", lambda _project_id: project)
    monkeypatch.setattr(main.isc_client, "list_templates", lambda _connection, _template_type: [email, slack, teams])

    response = main.list_isc_templates("default", connection["id"], "standard")

    assert [candidate["medium"] for candidate in response["templates"]] == ["EMAIL"]
    assert response["templates"][0]["key"] == "email-key"


def test_unrecognized_template_error_identifies_name_key_and_medium():
    from app.store import inspect_import

    with pytest.raises(StoreError) as error:
        inspect_import([{
            "name": "Access Request with ROBO",
            "key": "access_request_with_robo",
            "medium": "SLACK",
            "body": "{}",
            "subject": None,
        }])

    message = str(error.value)
    assert "Access Request with ROBO" in message
    assert "access_request_with_robo" in message
    assert "medium: SLACK" in message


def test_ai_key_is_persistent_but_never_returned_or_stored_in_project(tmp_path, monkeypatch):
    from app import ai_secrets, store
    from app.providers import registry

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ai_secrets, "ENV_PATH", tmp_path / ".env")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY_B64", raising=False)
    secret = "super-secret-test-key"
    response = put_ai_config(
        "secret-project",
        AIConfigUpdate(provider="openai", model="test-model", api_key=secret),
    )
    saved = (tmp_path / "secret-project.json").read_text(encoding="utf-8")
    saved_secrets = (tmp_path / ".env").read_text(encoding="utf-8")
    assert secret not in saved
    assert secret not in saved_secrets
    assert secret not in json.dumps(response)
    assert response["provider"]["key_configured"] is True
    registry._session_keys.clear()
    assert registry.api_key_for("secret-project", "openai") == secret
    put_ai_config("secret-project", AIConfigUpdate(provider="openai", model="another-model", api_key=""))
    registry._session_keys.clear()
    assert registry.api_key_for("secret-project", "openai") == secret


def test_legacy_instructions_are_moved_out_of_signature(tmp_path, monkeypatch):
    from app import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    instructions = (
        "Adaptar todo el texto visible al español neutro. "
        "No modificar variables Apache Velocity. "
        "Aplicar la estructura visual del HTML de referencia."
    )
    project = {
        "project_id": "legacy-instructions",
        "filename": "",
        "config": {"signature": instructions, "additional_instructions": ""},
        "items": [],
    }
    (tmp_path / "legacy-instructions.json").write_text(json.dumps(project), encoding="utf-8")
    loaded = store.load_project("legacy-instructions")
    assert loaded["config"]["signature"] == ""
    assert loaded["config"]["additional_instructions"] == instructions


def test_delete_notification_and_clear_panel(tmp_path, monkeypatch):
    from app import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    first = import_templates("delete-flow", ImportRequest(filename="sample.json", data=[SAMPLE]))
    first_id = first["templates"][0]["internal_id"]
    deleted = delete_template("delete-flow", first_id)
    assert deleted["deleted_id"] == first_id
    assert deleted["templates"] == []
    assert get_project("delete-flow")["filename"] == ""

    import_templates("delete-flow", ImportRequest(filename="sample.json", data=[SAMPLE, {**SAMPLE, "key": "second"}]))
    cleared = clear_templates("delete-flow")
    assert cleared == {"deleted": 2, "templates": []}
    project = get_project("delete-flow")
    assert project["templates"] == []
    assert project["filename"] == ""


def test_delete_isc_connection_removes_only_its_local_credentials(tmp_path, monkeypatch):
    from app import isc_secrets, store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(isc_secrets, "ENV_PATH", tmp_path / ".env")
    connection = create_isc_connection(
        "isc-delete",
        ISCConnectionInput(
            name="Tenant de prueba",
            environment="sandbox",
            api_base_url="https://tenant.api.identitynow.com",
            client_id="client-test",
            client_secret="secret-test",
        ),
    )
    env_before = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "client-test" not in env_before
    deleted = delete_isc_connection("isc-delete", connection["id"])
    assert deleted["deleted_id"] == connection["id"]
    assert (tmp_path / ".env").read_text(encoding="utf-8") == ""


def test_style_guide_api_marks_adaptations_outdated_and_invalidates_preparations(tmp_path, monkeypatch):
    from app import prompt_rules, store

    data = tmp_path / "data"
    guides = tmp_path / "guides"
    monkeypatch.setattr(store, "DATA_DIR", data)
    monkeypatch.setattr(prompt_rules, "PROJECT_RULES_DIR", guides)
    project = "guide-flow"
    imported = import_templates(project, ImportRequest(filename="sample.json", data=[SAMPLE]))
    internal_id = imported["templates"][0]["internal_id"]
    put_config(project, BrandingConfig(mode="preserve", old_client_name="Cliente Viejo", new_client_name="Cliente Nuevo"))
    adapted = adapt_template(project, AdaptRequest(internal_id=internal_id))
    assert adapted["config_outdated"] is False

    saved_project = store.load_project(project)
    saved_project["items"][0]["publication_preparation"] = {"preparation_id": "stale"}
    store.save_project(project, saved_project)
    guide = put_project_style_guide(project, StyleGuideUpdate(content="# Estilo\nUsar azul.", filename="cliente.md"))
    assert guide["configured"] is True
    assert guide["filename"] == "cliente.md"
    assert get_project(project)["templates"][0]["config_outdated"] is True
    assert get_template(project, internal_id)["publication_preparation"] is None
    assert get_project_style_guide(project)["content"].endswith("Usar azul.")

    cleared = delete_project_style_guide(project)
    assert cleared["configured"] is False

