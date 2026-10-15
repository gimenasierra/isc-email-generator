from __future__ import annotations

import os

from ..ai_secrets import get_persistent_key, set_persistent_key
from ..models import AIConfig
from .base import AdaptationProvider, ProviderError
from .mock import MockAdaptationProvider
from .remote import AnthropicProvider, GeminiProvider, GroqProvider, OpenAICompatibleProvider, OpenAIProvider


PROVIDERS: dict[str, AdaptationProvider] = {
    "simulated": MockAdaptationProvider(),
    "gemini": GeminiProvider(),
    "groq": GroqProvider(),
    "anthropic": AnthropicProvider(),
    "openai": OpenAIProvider(),
    "openai_compatible": OpenAICompatibleProvider(),
}

ENV_KEYS = {
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openai_compatible": "LOCAL_OPENAI_API_KEY",
}

_session_keys: dict[tuple[str, str], str] = {}
_connection_states: dict[tuple[str, str], dict[str, str]] = {}


def provider_for(settings: AIConfig) -> AdaptationProvider:
    try:
        return PROVIDERS[settings.provider]
    except KeyError as exc:
        raise ProviderError("El proveedor seleccionado no está disponible.") from exc


def set_session_key(project_id: str, provider_id: str, api_key: str) -> None:
    if api_key:
        _session_keys[(project_id, provider_id)] = api_key


def save_api_key(project_id: str, provider_id: str, api_key: str) -> None:
    if not api_key:
        return
    set_persistent_key(provider_id, api_key)
    _session_keys[(project_id, provider_id)] = api_key


def api_key_for(project_id: str, provider_id: str) -> str:
    session_key = _session_keys.get((project_id, provider_id), "")
    if session_key:
        return session_key
    try:
        return get_persistent_key(provider_id)
    except ValueError:
        return os.getenv(ENV_KEYS.get(provider_id, ""), "")


def key_configured(project_id: str, provider_id: str) -> bool:
    return bool(api_key_for(project_id, provider_id))


def connection_state(project_id: str, provider_id: str) -> dict[str, str]:
    return _connection_states.get((project_id, provider_id), {"status": "not_tested", "message": "Conexión todavía no probada."})


def set_connection_state(project_id: str, provider_id: str, status: str, message: str) -> None:
    _connection_states[(project_id, provider_id)] = {"status": status, "message": message}
