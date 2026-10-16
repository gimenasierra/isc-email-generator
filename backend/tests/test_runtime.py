from __future__ import annotations

import pytest

from app.runtime import app_port


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
