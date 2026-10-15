from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import AIConfig, BrandingConfig


class ProviderError(RuntimeError):
    """Safe provider error suitable for returning to the local UI."""


@dataclass(frozen=True)
class AdaptationResult:
    subject: str
    body: str
    changes: list[str]


@dataclass(frozen=True)
class ConnectionResult:
    message: str


@dataclass(frozen=True)
class TemplateContext:
    name: str
    key: str
    locale: str
    project_id: str = "default"
    protected_velocity_blocks: tuple[str, ...] = ()


ADAPTATION_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "changes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["subject", "body", "changes"],
    "additionalProperties": False,
}


class AdaptationProvider(ABC):
    name: str
    is_simulated: bool

    @abstractmethod
    def adapt(self, subject: str, body: str, config: BrandingConfig, settings: AIConfig, api_key: str, context: TemplateContext) -> AdaptationResult:
        """Return a normalized adaptation without modifying template metadata."""

    @abstractmethod
    def test_connection(self, settings: AIConfig, api_key: str) -> ConnectionResult:
        """Perform a minimal provider/model availability request."""

