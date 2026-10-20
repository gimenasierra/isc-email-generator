from __future__ import annotations

import pytest

from app.runtime import app_port
from app.paths import configured_state_dir, state_path


def test_app_port_defaults_to_8000(monkeypatch) -> None:
    monkeypatch.delenv("ISC_EMAIL_GENERATOR_PORT", raising=False)
    assert app_port() == 8000


def test_app_port_accepts_configured_value(monkeypatch) -> None:
    monkeypatch.setenv("ISC_EMAIL_GENERATOR_PORT", "8010")
    assert app_port() == 8010


@pytest.mark.parametrize("value", ["abc", "0", "65536", ""])
def test_app_port_rejects_invalid_values(monkeypatch, value: str) -> None:
    monkeypatch.setenv("ISC_EMAIL_GENERATOR_PORT", value)
    with pytest.raises(ValueError, match="ISC_EMAIL_GENERATOR_PORT"):
        app_port()


def test_state_paths_keep_development_defaults_without_override(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("ISC_EMAIL_GENERATOR_STATE_DIR", raising=False)
    default = tmp_path / "development" / "data"
    assert configured_state_dir() is None
    assert state_path("data", development_default=default) == default


def test_state_paths_use_configured_writable_directory(monkeypatch, tmp_path) -> None:
    state_dir = tmp_path / "portable state with spaces"
    monkeypatch.setenv("ISC_EMAIL_GENERATOR_STATE_DIR", str(state_dir))
    assert configured_state_dir() == state_dir
    assert state_path("prompts", "projects", development_default=tmp_path / "ignored") == state_dir / "prompts" / "projects"
