from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs

import httpx
import pytest

from app.isc import ISCClient, ISCError, ISCWriteUncertain, normalize_api_base_url
from app.isc_secrets import credential_status, get_credentials, set_credentials
from app.main import create_isc_connection
from app.models import ISCConnectionInput
from app.store import import_isc_templates


CONNECTION = {
    "id": "a" * 32,
    "name": "Cliente de prueba",
    "environment": "sandbox",
    "api_base_url": "https://tenant.api.identitynow.com",
}


def template(number: int = 1) -> dict:
    return {
        "id": f"remote-{number}",
        "name": f"Plantilla {number}",
        "key": f"key-{number}",
        "medium": "EMAIL",
        "locale": "es",
        "subject": "Hola $name",
        "body": "<p>#if($name)Hola $name#end</p>",
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://acme.api.identitynow.com", "https://acme.api.identitynow.com"),
        (" https://acme.api.identitynow-demo.com/ ", "https://acme.api.identitynow-demo.com"),
    ],
)
def test_normalizes_allowed_isc_urls(value, expected):
    assert normalize_api_base_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "http://acme.api.identitynow.com",
        "https://evil.example.com",
        "https://user:secret@acme.api.identitynow.com",
        "https://acme.api.identitynow.com:443",
        "https://acme.api.identitynow.com/api",
        "https://acme.api.identitynow.com?next=https://evil.example",
        "https://acme.api.identitynow.com/#fragment",
    ],
)
def test_rejects_unsafe_isc_urls(value):
    with pytest.raises(ValueError):
        normalize_api_base_url(value)


def test_secret_file_preserves_other_values_and_blank_keeps_credentials(tmp_path):
    path = tmp_path / ".env"
    path.write_text("UNRELATED=value\n", encoding="utf-8")
    set_credentials(CONNECTION["id"], "client-id", "client-secret", path)
    contents = path.read_text(encoding="utf-8")
    assert "UNRELATED=value" in contents
    assert "client-id" not in contents
    assert "client-secret" not in contents
    assert get_credentials(CONNECTION["id"], path) == ("client-id", "client-secret")
    set_credentials(CONNECTION["id"], "", "", path)
    assert get_credentials(CONNECTION["id"], path) == ("client-id", "client-secret")
    assert credential_status(CONNECTION["id"], path) == (True, True)


def test_concurrent_isc_secret_writes_do_not_overwrite_other_connections(tmp_path):
    path = tmp_path / ".env"
    connection_ids = [f"{index:032x}" for index in range(1, 17)]

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda connection_id: set_credentials(connection_id, f"client-{connection_id}", f"secret-{connection_id}", path), connection_ids))

    for connection_id in connection_ids:
        assert get_credentials(connection_id, path) == (f"client-{connection_id}", f"secret-{connection_id}")


def test_token_form_cache_and_expiration():
    calls = []
    clock = [1000.0]

    def handler(request: httpx.Request):
        calls.append(request)
        form = parse_qs(request.content.decode())
        assert form == {"grant_type": ["client_credentials"], "client_id": ["client"], "client_secret": ["secret"]}
        return httpx.Response(200, json={"access_token": f"token-{len(calls)}", "expires_in": 120})

    client = ISCClient(httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False), now=lambda: clock[0], credentials=lambda _: ("client", "secret"))
    assert client.token(CONNECTION) == "token-1"
    assert client.token(CONNECTION) == "token-1"
    clock[0] += 61
    assert client.token(CONNECTION) == "token-2"
    assert len(calls) == 2


def test_lists_all_pages_with_email_filter():
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer token"
        assert "filters" not in request.url.params
        offset = int(request.url.params["offset"])
        page = [template(index) for index in range(offset, min(offset + 250, 251))]
        return httpx.Response(200, json=page, headers={"X-Total-Count": "251"})

    client = ISCClient(httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False), credentials=lambda _: ("client", "secret"))
    result = client.list_templates(CONNECTION, "custom")
    assert len(result) == 251
    assert [request.url.params.get("offset") for request in requests if request.method == "GET"] == ["0", "250"]


def test_refreshes_once_after_401():
    token_calls = 0
    get_calls = 0

    def handler(request: httpx.Request):
        nonlocal token_calls, get_calls
        if request.url.path == "/oauth/token":
            token_calls += 1
            return httpx.Response(200, json={"access_token": f"token-{token_calls}", "expires_in": 3600})
        get_calls += 1
        if get_calls == 1:
            return httpx.Response(401, json={})
        assert request.headers["Authorization"] == "Bearer token-2"
        return httpx.Response(200, json=[])

    client = ISCClient(httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False), credentials=lambda _: ("client", "secret"))
    assert client.list_templates(CONNECTION, "standard") == []
    assert token_calls == 2
    assert get_calls == 2


def test_reports_denied_endpoint_without_inventing_scope_and_limits_429_retries():
    sleeps = []
    mode = ["forbidden"]
    get_calls = 0

    def handler(request: httpx.Request):
        nonlocal get_calls
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        get_calls += 1
        if mode[0] == "forbidden":
            return httpx.Response(403, json={})
        return httpx.Response(429, json={}, headers={"Retry-After": "2"})

    client = ISCClient(httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False), sleep=sleeps.append, credentials=lambda _: ("client", "secret"))
    with pytest.raises(ISCError, match="ISC denegó el acceso a las plantillas personalizadas") as forbidden:
        client.list_templates(CONNECTION, "custom")
    assert forbidden.value.status_code == 403
    assert "sp:scopes:all" in str(forbidden.value)
    assert "idn:notification" not in str(forbidden.value)
    mode[0] = "limited"
    get_calls = 0
    with pytest.raises(ISCError, match="limitando") as limited:
        client.list_templates(CONNECTION, "custom")
    assert limited.value.status_code == 429
    assert get_calls == 3
    assert sleeps == [2.0, 2.0]


def test_publication_refreshes_401_retries_429_and_uses_json_headers():
    token_calls = post_calls = 0
    sleeps = []

    def handler(request: httpx.Request):
        nonlocal token_calls, post_calls
        if request.url.path == "/oauth/token":
            token_calls += 1
            return httpx.Response(200, json={"access_token": f"token-{token_calls}", "expires_in": 3600})
        post_calls += 1
        assert request.method == "POST"
        assert request.headers["Accept"] == "application/json"
        assert request.headers["Content-Type"] == "application/json"
        if post_calls == 1:
            return httpx.Response(401, json={})
        assert request.headers["Authorization"] == "Bearer token-2"
        if post_calls == 2:
            return httpx.Response(429, json={}, headers={"Retry-After": "1"})
        return httpx.Response(200, json=template())

    client = ISCClient(httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False), sleep=sleeps.append, credentials=lambda _: ("client", "secret"))
    assert client.create_notification_template(CONNECTION, template())["id"] == "remote-1"
    assert token_calls == 2
    assert post_calls == 3
    assert sleeps == [1.0]


def test_publication_timeout_is_marked_uncertain():
    def handler(request: httpx.Request):
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        raise httpx.ReadTimeout("after send", request=request)

    client = ISCClient(httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False), credentials=lambda _: ("client", "secret"))
    with pytest.raises(ISCWriteUncertain, match="comprobarse"):
        client.create_notification_template(CONNECTION, template())


def test_import_duplicate_can_skip_or_replace_and_never_merges_result():
    original = template()
    project = {
        "items": [{
            "internal_id": "template-1",
            "original": original,
            "result": {**original, "subject": "Adaptado"},
            "validation": {"suspicious": False},
            "actions": ["adapted"],
            "adaptation_config_signature": "old",
        }]
    }
    provenance = {"connection_id": CONNECTION["id"], "connection_name": "Cliente", "api_base_url": CONNECTION["api_base_url"], "environment": "sandbox", "template_type": "custom"}
    changed = {**original, "name": "Nueva versión"}
    skipped = import_isc_templates(project, [changed], provenance, "skip")
    assert skipped == {"imported": 0, "skipped": 1, "replaced": 0, "copied": 0, "adaptations_removed": 0, "internal_ids": []}
    assert project["items"][0]["result"]["subject"] == "Adaptado"
    replaced = import_isc_templates(project, [changed], provenance, "replace")
    assert replaced["adaptations_removed"] == 1
    assert replaced["replaced"] == 1
    assert project["items"][0]["result"] is None
    assert project["items"][0]["original"]["name"] == "Nueva versión"
    serialized = json.dumps(project)
    assert "client-secret" not in serialized


def test_import_duplicate_as_independent_local_copy():
    original = template()
    project = {
        "items": [{
            "internal_id": "template-1",
            "original": original,
            "result": {**original, "subject": "Adaptado"},
            "validation": None,
            "actions": [],
            "adaptation_config_signature": "current",
        }]
    }
    provenance = {"connection_id": CONNECTION["id"], "connection_name": "Cliente", "api_base_url": CONNECTION["api_base_url"], "environment": "sandbox", "template_type": "custom"}

    copied = import_isc_templates(project, [{**original, "name": "Copia importada"}], provenance, "copy")

    assert copied["imported"] == 1
    assert copied["copied"] == 1
    assert copied["replaced"] == 0
    assert len(project["items"]) == 2
    assert project["items"][0]["result"]["subject"] == "Adaptado"
    assert project["items"][1]["internal_id"] == "template-2"
    assert project["items"][1]["local_copy"] is True
    assert project["items"][1]["result"] is None
    assert project["items"][1]["original"]["key"] == original["key"]


def test_connection_response_and_project_never_contain_credentials(tmp_path, monkeypatch):
    from app import isc_secrets, store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(isc_secrets, "ENV_PATH", tmp_path / ".env")
    response = create_isc_connection(
        "safe-project",
        ISCConnectionInput(
            name="Tenant seguro",
            environment="production",
            api_base_url="https://safe.api.identitynow.com/",
            client_id="visible-only-on-input",
            client_secret="never-return-this-secret",
        ),
    )
    assert response["client_id_configured"] is True
    assert response["secret_configured"] is True
    serialized_response = json.dumps(response)
    serialized_project = (tmp_path / "data" / "safe-project.json").read_text(encoding="utf-8")
    assert "visible-only-on-input" not in serialized_response
    assert "never-return-this-secret" not in serialized_response
    assert "visible-only-on-input" not in serialized_project
    assert "never-return-this-secret" not in serialized_project
