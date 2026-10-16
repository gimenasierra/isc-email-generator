from __future__ import annotations

import json

import pytest

from app.isc import ISCError, ISCWriteUncertain
from app.publication import local_signature, prepare_item, publish_prepared, reference_warnings, reverify_publication
from app.store import summary


CONNECTION = {
    "id": "destination",
    "name": "Tenant destino",
    "environment": "sandbox",
    "api_base_url": "https://destination.api.identitynow.com",
}
CONFIG = {
    "old_client_name": "Cliente viejo",
    "new_client_name": "Cliente nuevo",
    "old_logo_url": "",
    "new_logo_url": "",
    "email_mappings": [],
    "url_mappings": [],
}


def template(*, identifier: str = "destination-id", subject: str = "Destino", body: str = "<p>Destino</p>") -> dict:
    return {
        "id": identifier,
        "name": "Approval Reminder",
        "key": "approval_reminder",
        "medium": "EMAIL",
        "locale": "es",
        "subject": subject,
        "body": body,
        "from": "$__global.emailFromAddress",
        "replyTo": "soporte@destino.example",
        "created": "2026-01-01T00:00:00Z",
        "modified": "2026-01-02T00:00:00Z",
        "header": None,
        "footer": None,
    }


def item() -> dict:
    original = {**template(identifier="origin-id"), "subject": "Original $name", "body": "<p>Original $name</p>"}
    result = {**original, "subject": 'Adaptado "especial" $name', "body": "<p>Línea 1\n$name</p>"}
    return {
        "internal_id": "template-1",
        "original": original,
        "result": result,
        "validation": {
            "missing_variables": [],
            "added_variables": [],
            "missing_directives": [],
            "added_directives": [],
            "pending_old_client_references": [],
        },
        "publication_preparation": None,
        "publication_backups": [],
        "publication_history": [],
    }


class FakeISC:
    def __init__(self, custom=None, default=None):
        self.custom = list(custom or [])
        self.default = list(default or [])
        self.posts = []

    def find_template_matches(self, connection, template_type, key, medium, locale):
        values = self.custom if template_type == "custom" else self.default
        return [value.copy() for value in values if (value["key"], value["medium"], value["locale"]) == (key, medium, locale)]

    def create_notification_template(self, connection, payload):
        self.posts.append(json.loads(json.dumps(payload)))
        saved = {**payload, "id": payload.get("id", "created-id"), "modified": "2026-10-14T00:00:00Z"}
        self.custom = [saved]
        return saved.copy()


def project(local_item: dict) -> dict:
    return {"project_id": "p", "config": CONFIG.copy(), "items": [local_item]}


def saver(saved):
    def save(project_id, value):
        saved.append(json.loads(json.dumps(value)))
    return save


def test_prepares_from_custom_and_preserves_destination_fields_not_origin_id():
    local_item = item()
    client = FakeISC(custom=[template()])
    prepared = prepare_item(local_item, CONFIG, CONNECTION, client)
    assert prepared["mode"] == "replace_custom"
    assert prepared["payload"]["id"] == "destination-id"
    assert prepared["payload"]["id"] != local_item["original"]["id"]
    assert prepared["payload"]["from"] == "$__global.emailFromAddress"
    assert prepared["payload"]["replyTo"] == "soporte@destino.example"
    assert prepared["payload"]["locale"] == "es"
    assert "created" not in prepared["payload"]
    assert "modified" not in prepared["payload"]
    assert "header" not in prepared["payload"]
    assert "footer" not in prepared["payload"]
    serialized = json.dumps(prepared["payload"], ensure_ascii=False)
    assert json.loads(serialized)["subject"] == 'Adaptado "especial" $name'
    assert "\n$name" in json.loads(serialized)["body"]


def test_prepares_from_default_without_copying_default_or_origin_id():
    local_item = item()
    prepared = prepare_item(local_item, CONFIG, CONNECTION, FakeISC(default=[template(identifier="default-id")]))
    assert prepared["mode"] == "create_from_default"
    assert "id" not in prepared["payload"]


def test_prepares_from_known_custom_id_when_collection_omits_it():
    destination = template(identifier="known-custom-id")

    class DirectReadISC(FakeISC):
        def get_template_by_id(self, connection, template_type, template_id):
            assert template_type == "custom"
            return destination.copy() if template_id == "known-custom-id" else None

    local_item = item()
    prepared = prepare_item(
        local_item,
        CONFIG,
        CONNECTION,
        DirectReadISC(default=[template(identifier="default-id")]),
        ["known-custom-id"],
    )
    assert prepared["mode"] == "replace_custom"
    assert prepared["target_current"]["id"] == "known-custom-id"
    assert prepared["target_current"]["subject"] == "Destino"
    assert prepared["payload"]["id"] == "known-custom-id"


def test_warns_about_hardcoded_url_for_another_isc_tenant():
    local_item = item()
    local_item["result"]["body"] += '<a href="https://source.identitynow.com/ui">Origen</a>'
    warnings = reference_warnings(local_item["result"], CONFIG, local_item["validation"], CONNECTION)
    assert any("source.identitynow.com" in warning for warning in warnings)


@pytest.mark.parametrize(
    ("custom", "default", "message"),
    [
        ([], [], "No existe"),
        ([template(identifier="a"), template(identifier="b")], [], "personalizaciones"),
        ([], [template(identifier="a"), template(identifier="b")], "estándar"),
    ],
)
def test_blocks_missing_or_ambiguous_destination(custom, default, message):
    with pytest.raises(ISCError, match=message):
        prepare_item(item(), CONFIG, CONNECTION, FakeISC(custom=custom, default=default))


def test_publish_blocks_when_destination_changed_since_preparation():
    local_item = item()
    client = FakeISC(custom=[template()])
    prepared = prepare_item(local_item, CONFIG, CONNECTION, client)
    client.custom[0]["subject"] = "Cambio concurrente"
    saved = []
    with pytest.raises(ISCError, match="cambió desde la preparación"):
        publish_prepared("p", project(local_item), local_item, CONNECTION, prepared["preparation_id"], client, saver(saved))
    assert not client.posts
    assert local_item["publication_preparation"] is None


def test_publish_saves_backup_and_verifies_each_field():
    local_item = item()
    client = FakeISC(custom=[template()])
    prepared = prepare_item(local_item, CONFIG, CONNECTION, client)
    saved = []
    record = publish_prepared("p", project(local_item), local_item, CONNECTION, prepared["preparation_id"], client, saver(saved))
    assert record["status"] == "published_verified"
    assert len(client.posts) == 1
    assert local_item["publication_backups"][0]["state"] == "customization"
    assert local_item["publication_backups"][0]["template"]["subject"] == "Destino"
    assert local_item["publication_history"][-1]["status"] == "published_verified"
    assert record["write_acknowledged"] is True
    assert record["local_signature"] == local_signature(local_item, CONFIG)
    assert local_item["publication_preparation"] is None


def test_timeout_checks_destination_and_recognizes_effective_publication():
    class TimeoutAfterSave(FakeISC):
        def create_notification_template(self, connection, payload):
            saved = {**payload, "id": payload.get("id", "created-id")}
            self.custom = [saved]
            raise ISCWriteUncertain("timeout")

    local_item = item()
    client = TimeoutAfterSave(default=[template(identifier="default-id")])
    prepared = prepare_item(local_item, CONFIG, CONNECTION, client)
    record = publish_prepared("p", project(local_item), local_item, CONNECTION, prepared["preparation_id"], client, saver([]))
    assert record["status"] == "published_verified"
    assert record["response"] is None
    assert record["verification"]["subject"] == local_item["result"]["subject"]


def test_verification_retries_until_new_customization_is_visible():
    class EventuallyConsistentISC(FakeISC):
        verification_reads = 0

        def find_template_matches(self, connection, template_type, key, medium, locale):
            if template_type == "custom" and self.posts:
                self.verification_reads += 1
                if self.verification_reads < 3:
                    return []
            return super().find_template_matches(connection, template_type, key, medium, locale)

    local_item = item()
    client = EventuallyConsistentISC(default=[template(identifier="default-id")])
    prepared = prepare_item(local_item, CONFIG, CONNECTION, client)
    record = publish_prepared("p", project(local_item), local_item, CONNECTION, prepared["preparation_id"], client, saver([]))
    assert record["status"] == "published_verified"
    assert record["verification"]["id"] == "created-id"
    assert client.verification_reads == 3


def test_timeout_without_matching_destination_is_unconfirmed_not_retried():
    class TimeoutWithoutSave(FakeISC):
        calls = 0

        def create_notification_template(self, connection, payload):
            self.calls += 1
            raise ISCWriteUncertain("timeout")

    local_item = item()
    client = TimeoutWithoutSave(default=[template(identifier="default-id")])
    prepared = prepare_item(local_item, CONFIG, CONNECTION, client)
    record = publish_prepared("p", project(local_item), local_item, CONNECTION, prepared["preparation_id"], client, saver([]))
    assert record["status"] == "result_unconfirmed"
    assert record["write_acknowledged"] is False
    assert client.calls == 1


def test_successful_post_without_readback_reports_the_created_id():
    class AcceptedButNotVisible(FakeISC):
        def find_template_matches(self, connection, template_type, key, medium, locale):
            if template_type == "custom" and self.posts:
                return []
            return super().find_template_matches(connection, template_type, key, medium, locale)

    local_item = item()
    client = AcceptedButNotVisible(default=[template(identifier="default-id")])
    prepared = prepare_item(local_item, CONFIG, CONNECTION, client)
    record = publish_prepared("p", project(local_item), local_item, CONNECTION, prepared["preparation_id"], client, saver([]))
    assert record["status"] == "published_pending_verification"
    assert record["write_acknowledged"] is True
    assert "created-id" in record["message"]
    assert "sin volver a publicar" in record["message"]

    still_pending = reverify_publication("p", project(local_item), local_item, CONNECTION, record["publication_id"], client, saver([]))
    assert still_pending["status"] == "published_pending_verification"
    assert "no se realizó una nueva escritura" in still_pending["message"]

    client.find_template_matches = FakeISC.find_template_matches.__get__(client, AcceptedButNotVisible)
    verified = reverify_publication("p", project(local_item), local_item, CONNECTION, record["publication_id"], client, saver([]))
    assert verified["status"] == "published_verified"
    assert verified["verification"]["id"] == "created-id"


def test_successful_post_is_verified_by_direct_id_when_collection_omits_it():
    class DirectlyVisibleISC(FakeISC):
        def find_template_matches(self, connection, template_type, key, medium, locale):
            if template_type == "custom" and self.posts:
                return []
            return super().find_template_matches(connection, template_type, key, medium, locale)

        def get_template_by_id(self, connection, template_type, template_id):
            if template_type == "custom" and self.custom and self.custom[0].get("id") == template_id:
                return self.custom[0].copy()
            return None

    local_item = item()
    client = DirectlyVisibleISC(default=[template(identifier="default-id")])
    prepared = prepare_item(local_item, CONFIG, CONNECTION, client)
    record = publish_prepared("p", project(local_item), local_item, CONNECTION, prepared["preparation_id"], client, saver([]))
    assert record["status"] == "published_verified"
    assert record["verification"]["id"] == "created-id"


def test_publication_summary_is_current_until_the_result_changes():
    local_item = item()
    client = FakeISC(custom=[template()])
    prepared = prepare_item(local_item, CONFIG, CONNECTION, client)
    publish_prepared("p", project(local_item), local_item, CONNECTION, prepared["preparation_id"], client, saver([]))

    current = summary(local_item, CONFIG).model_dump()
    assert current["publication_states"][0]["applies_to_current_result"] is True
    assert current["publication_states"][0]["connection"]["id"] == CONNECTION["id"]

    local_item["result"]["subject"] = "Nueva versión $name"
    modified = summary(local_item, CONFIG).model_dump()
    assert modified["publication_states"][0]["applies_to_current_result"] is False


def test_legacy_unconfirmed_record_with_response_id_is_treated_as_accepted(tmp_path, monkeypatch):
    from app import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    local_item = item()
    local_item["publication_history"] = [
        {
            "publication_id": "legacy-publication",
            "status": "result_unconfirmed",
            "connection": CONNECTION.copy(),
            "response": {"id": "accepted-id"},
            "payload": {"subject": local_item["result"]["subject"], "body": local_item["result"]["body"]},
            "message": "Resultado no confirmado",
            "differences": [],
        }
    ]
    store.save_project("legacy", {"project_id": "legacy", "config": CONFIG, "items": [local_item]})

    loaded = store.load_project("legacy")
    migrated = loaded["items"][0]["publication_history"][0]
    assert migrated["status"] == "published_pending_verification"
    assert migrated["write_acknowledged"] is True
    assert "accepted-id" in migrated["message"]


def test_batch_can_finish_partially_and_keeps_failed_preparation(tmp_path, monkeypatch):
    from app import main, store
    from app.main import adapt_template, import_templates, prepare_publication_batch, publish_publication_batch
    from app.models import AdaptRequest, ImportRequest, PublicationBatchConfirmRequest, PublicationBatchPrepareRequest

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    first = item()["original"]
    second = {**first, "id": "origin-2", "name": "Segundo", "key": "second_key"}
    imported = import_templates("batch", ImportRequest(filename="batch.json", data=[first, second]))
    for summary in imported["templates"]:
        adapt_template("batch", AdaptRequest(internal_id=summary["internal_id"]))

    class BatchISC:
        def __init__(self):
            self.custom = {}

        def find_template_matches(self, connection, template_type, key, medium, locale):
            if template_type == "custom":
                return [self.custom[key].copy()] if key in self.custom else []
            return [{**template(identifier=f"default-{key}"), "key": key}] if template_type == "standard" else []

        def create_notification_template(self, connection, payload):
            if payload["key"] == "second_key":
                raise ISCError("falla simulada", 502)
            saved = {**payload, "id": "created-first"}
            self.custom[payload["key"]] = saved
            return saved.copy()

    monkeypatch.setattr(main, "isc_client", BatchISC())
    stored = store.load_project("batch")
    stored["isc_connections"] = [CONNECTION.copy()]
    store.save_project("batch", stored)
    ids = [summary["internal_id"] for summary in imported["templates"]]
    prepared = prepare_publication_batch("batch", PublicationBatchPrepareRequest(connection_id=CONNECTION["id"], internal_ids=ids))
    assert [entry["status"] for entry in prepared["items"]] == ["ready", "ready"]
    confirmed = publish_publication_batch(
        "batch",
        PublicationBatchConfirmRequest(
            connection_id=CONNECTION["id"],
            items=[{"internal_id": entry["internal_id"], "preparation_id": entry["preparation"]["preparation_id"]} for entry in prepared["items"]],
        ),
    )
    assert confirmed["transactional"] is False
    assert [entry["status"] for entry in confirmed["items"]] == ["published_verified", "failed"]
    reloaded = store.load_project("batch")
    assert reloaded["items"][0]["publication_preparation"] is None
    assert reloaded["items"][1]["publication_preparation"] is not None


def test_batch_blocks_two_local_copies_for_the_same_isc_destination(tmp_path, monkeypatch):
    from app import main, store
    from app.main import adapt_template, import_templates, prepare_publication_batch
    from app.models import AdaptRequest, ImportRequest, PublicationBatchPrepareRequest

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    original = item()["original"]
    imported = import_templates("duplicates", ImportRequest(filename="duplicates.json", data=[original, {**original, "name": "Copia local"}], duplicate_strategy="copy"))
    for summary in imported["templates"]:
        adapt_template("duplicates", AdaptRequest(internal_id=summary["internal_id"]))

    monkeypatch.setattr(main, "isc_client", FakeISC(default=[template(identifier="default-id")]))
    stored = store.load_project("duplicates")
    stored["isc_connections"] = [CONNECTION.copy()]
    store.save_project("duplicates", stored)
    ids = [summary["internal_id"] for summary in imported["templates"]]

    prepared = prepare_publication_batch(
        "duplicates",
        PublicationBatchPrepareRequest(connection_id=CONNECTION["id"], internal_ids=ids),
    )

    assert [entry["status"] for entry in prepared["items"]] == ["ready", "blocked"]
    assert "mismo key + medium + locale" in prepared["items"][1]["error"]


def test_edit_and_branding_change_invalidate_previous_preparation(tmp_path, monkeypatch):
    from app import store
    from app.main import edit_result, put_config
    from app.models import BrandingConfig, EditResultRequest

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    local_item = item()
    local_item["publication_preparation"] = {"preparation_id": "stale"}
    value = {
        "project_id": "invalidate",
        "filename": "",
        "config": BrandingConfig().model_dump(),
        "ai_config": {"provider": "simulated", "model": "", "base_url": ""},
        "isc_connections": [],
        "items": [local_item],
    }
    store.save_project("invalidate", value)
    edit_result("invalidate", "template-1", EditResultRequest(subject="Editado $name", body="<p>Editado $name</p>"))
    assert store.load_project("invalidate")["items"][0]["publication_preparation"] is None

    value = store.load_project("invalidate")
    value["items"][0]["publication_preparation"] = {"preparation_id": "stale-again"}
    store.save_project("invalidate", value)
    put_config("invalidate", BrandingConfig(new_client_name="Otro cliente"))
    assert store.load_project("invalidate")["items"][0]["publication_preparation"] is None

