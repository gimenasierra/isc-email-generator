from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app import server_runtime
from app.admin_cli import project_report


@pytest.fixture()
def server(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(server_runtime, "SERVER_MODE", True)
    monkeypatch.setattr(server_runtime, "DATABASE_URL", f"sqlite:///{tmp_path / 'server.db'}")
    monkeypatch.setenv("ISC_EMAIL_GENERATOR_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    server_runtime.initialize()
    yield server_runtime
    if server_runtime._engine is not None:
        server_runtime._engine.dispose()


def test_temporary_password_and_session_invalidation(server):
    user = server.create_user("ana", "Temporal-1234", must_change=True)
    authenticated, token, csrf = server.authenticate("ana", "Temporal-1234")
    assert authenticated["must_change_password"] is True
    assert server.session_user(token)["id"] == user["id"]
    assert server.validate_csrf(token, csrf)
    server.current_user_id.set(user["id"])
    server.change_password(user["id"], "Temporal-1234", "Definitiva-5678")
    assert server.session_user(token) is None
    authenticated, token, _ = server.authenticate("ana", "Definitiva-5678")
    assert authenticated["must_change_password"] is False
    server.admin_set_active(user["id"], False)
    assert server.session_user(token) is None


def test_secrets_are_isolated_and_wrong_master_key_does_not_overwrite(server, monkeypatch):
    first = server.create_user("uno", "Temporal-1234")
    second = server.create_user("dos", "Temporal-1234")
    token = server.current_user_id.set(first["id"])
    server.set_secret("ai", "gemini", "key-one")
    assert server.get_secret("ai", "gemini") == "key-one"
    server.current_user_id.reset(token)
    token = server.current_user_id.set(second["id"])
    assert server.get_secret("ai", "gemini") == ""
    server.current_user_id.reset(token)
    monkeypatch.setenv("ISC_EMAIL_GENERATOR_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    with pytest.raises(server.SecretUnavailableError):
        server._verify_master_key()
    token = server.current_user_id.set(first["id"])
    with pytest.raises(server.SecretUnavailableError):
        server.get_secret("ai", "gemini")
    server.current_user_id.reset(token)


def test_optimistic_project_version_rejects_stale_update(server):
    user = server.create_user("editor", "Temporal-1234")
    token = server.current_user_id.set(user["id"])
    server.expected_project_version.set(0)
    assert server.save_project_state("default", {"value": 1}) == 1
    server.expected_project_version.set(1)
    assert server.save_project_state("default", {"value": 2}) == 2
    server.expected_project_version.set(1)
    with pytest.raises(server.ConcurrentUpdateError):
        server.save_project_state("default", {"value": 3})
    project, version = server.load_project_state("default", {})
    assert project == {"value": 2}
    assert version == 2
    server.current_user_id.reset(token)


def test_style_guide_rejects_stale_version(server):
    user = server.create_user("guide-editor", "Temporal-1234")
    token = server.current_user_id.set(user["id"])
    server.expected_style_guide_version.set(0)
    saved = server.save_style_guide_state("default", "# Primera", "guide.md")
    assert saved["version"] == 1
    server.expected_style_guide_version.set(1)
    assert server.save_style_guide_state("default", "# Segunda", "guide.md")["version"] == 2
    server.expected_style_guide_version.set(1)
    with pytest.raises(server.ConcurrentUpdateError):
        server.save_style_guide_state("default", "# Obsoleta", "guide.md")
    assert server.get_style_guide_state("default")["content"] == "# Segunda"
    server.current_user_id.reset(token)


def test_migration_report_is_dry_run_and_excludes_transient_state(tmp_path: Path):
    source = tmp_path / "default.json"
    original = {
        "project_id": "default",
        "items": [{"result": {"subject": "A"}, "publication_history": [{}], "publication_preparation": {"id": "temporary"}}],
        "isc_connections": [{"id": "abc", "status": "connected", "status_message": "ok"}],
    }
    source.write_text(__import__("json").dumps(original), encoding="utf-8")
    report, content = project_report(source, None)
    assert report["templates"] == 1
    assert report["connections_without_secrets"] == 1
    assert report["confirmation_hash"]
    assert content["project"]["items"][0]["publication_preparation"] is None
    assert __import__("json").loads(source.read_text(encoding="utf-8")) == original
