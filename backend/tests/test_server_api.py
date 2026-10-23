from __future__ import annotations

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import server_runtime
from app.main import app


def test_server_login_password_gate_and_optimistic_conflict(tmp_path, monkeypatch):
    monkeypatch.setattr(server_runtime, "SERVER_MODE", True)
    monkeypatch.setattr(server_runtime, "DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("ISC_EMAIL_GENERATOR_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setenv("ISC_EMAIL_GENERATOR_SECURE_COOKIES", "0")
    server_runtime.initialize()
    server_runtime.create_user("admin", "Temporal-1234", "admin", True)

    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "admin", "password": "Temporal-1234"})
        assert login.status_code == 200
        csrf = login.json()["csrf_token"]
        assert client.get("/api/projects/default").status_code == 403

        changed = client.post(
            "/api/auth/change-password",
            headers={"X-CSRF-Token": csrf},
            json={"current_password": "Temporal-1234", "new_password": "Definitiva-5678"},
        )
        assert changed.status_code == 200
        assert client.get("/api/auth/me").status_code == 401

        login = client.post("/api/auth/login", json={"username": "admin", "password": "Definitiva-5678"})
        csrf = login.json()["csrf_token"]
        project = client.get("/api/projects/default")
        assert project.status_code == 200
        assert project.json()["project_version"] == 0

        template = {"name": "Test", "key": "test", "medium": "EMAIL", "locale": "en", "subject": "Hello", "body": "<p>Hello</p>"}
        imported = client.post(
            "/api/projects/default/import",
            headers={"X-CSRF-Token": csrf, "X-Project-Version": "0"},
            json={"filename": "test.json", "data": template},
        )
        assert imported.status_code == 200
        assert imported.headers["X-Project-Version"] == "1"

        stale = client.post(
            "/api/projects/default/import",
            headers={"X-CSRF-Token": csrf, "X-Project-Version": "0"},
            json={"filename": "test-2.json", "data": {**template, "key": "test-2"}},
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "concurrent_update"
