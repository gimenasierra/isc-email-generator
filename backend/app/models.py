from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, field_validator, model_validator


class MappingEntry(BaseModel):
    source: str = ""
    target: str = ""


class BrandingConfig(BaseModel):
    target_language: str = "Español neutro"
    generate_missing_title: bool = True
    old_client_name: str = ""
    new_client_name: str = ""
    product_display_name: str = ""
    old_logo_url: str = ""
    new_logo_url: str = ""
    color_instructions: str = ""
    color_mappings: list[MappingEntry] = Field(default_factory=list)
    greeting: str = ""
    treatment: str = ""
    signature: str = ""
    email_mappings: list[MappingEntry] = Field(default_factory=list)
    url_mappings: list[MappingEntry] = Field(default_factory=list)
    additional_instructions: str = ""
    mode: Literal["preserve", "guide"] = "preserve"

    @model_validator(mode="before")
    @classmethod
    def migrate_reference_mode(cls, value: Any):
        if isinstance(value, dict) and value.get("mode") == "reference":
            value = {**value, "mode": "guide"}
            value.pop("reference_html", None)
        return value


class StyleGuideUpdate(BaseModel):
    content: str
    filename: str = ""


AIProviderId = Literal["simulated", "gemini", "groq", "anthropic", "openai", "openai_compatible"]


class AIConfig(BaseModel):
    provider: AIProviderId = "simulated"
    model: str = ""
    base_url: str = ""

    @model_validator(mode="after")
    def normalize_local_openai_url(self):
        if self.provider != "openai_compatible":
            self.base_url = ""
            return self
        if not self.base_url.strip():
            self.base_url = ""
            return self
        value = self.base_url.strip()
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("La URL base local debe comenzar con http:// o https:// e incluir un host.")
        if parsed.query or parsed.fragment:
            raise ValueError("La URL base local no debe incluir parámetros ni fragmentos.")
        path = parsed.path.rstrip("/")
        if path in {"", "/"}:
            path = "/v1"
        if path.casefold() == "/api/v1":
            raise ValueError(
                "Esa URL corresponde a la API nativa de LM Studio. Para este proveedor usá la API OpenAI-compatible: http://127.0.0.1:1234/v1."
            )
        if path.casefold().endswith(("/chat/completions", "/responses", "/models")):
            raise ValueError("Ingresá la URL base hasta /v1, sin agregar el endpoint final.")
        self.base_url = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
        return self


class AIConfigUpdate(AIConfig):
    api_key: str = ""


class AIConnectionTestRequest(AIConfig):
    api_key: str = ""


class LocalImportFile(BaseModel):
    filename: str
    data: Any


class ImportRequest(BaseModel):
    # filename/data preserve compatibility with clients that upload one JSON.
    filename: str = ""
    data: Any = None
    files: list[LocalImportFile] = Field(default_factory=list)
    duplicate_strategy: Literal["skip", "copy"] = "skip"

    @model_validator(mode="after")
    def require_input(self):
        if not self.files and not self.filename:
            raise ValueError("Se debe incluir al menos un archivo JSON.")
        return self


ISCEnvironment = Literal["sandbox", "production", "demo"]
ISCTemplateType = Literal["standard", "custom"]


class ISCConnectionInput(BaseModel):
    name: str
    environment: ISCEnvironment
    api_base_url: str
    client_id: str = ""
    client_secret: str = ""


class ISCImportRequest(BaseModel):
    template_type: ISCTemplateType
    templates: list[dict[str, Any]]
    duplicate_strategy: Literal["skip", "replace", "copy"] = "skip"


class TemplateSummary(BaseModel):
    internal_id: str
    name: str
    key: str
    medium: str
    locale: str
    has_result: bool = False
    config_outdated: bool = False
    unsafe_result: bool = False
    local_copy: bool = False
    source_filename: str = ""
    provenance: dict[str, Any] | None = None
    publication_states: list[dict[str, Any]] = Field(default_factory=list)


class ValidationReport(BaseModel):
    original_variables: list[str]
    result_variables: list[str]
    missing_variables: list[str]
    added_variables: list[str]
    repeated_variables: list[str] = Field(default_factory=list)
    original_directives: list[str]
    result_directives: list[str]
    missing_directives: list[str]
    added_directives: list[str]
    directive_order_changed: bool = False
    modified_protected_blocks: list[str] = Field(default_factory=list)
    pending_old_client_references: list[str]
    suspicious: bool
    disclaimer: str = (
        "Esta comparación es una ayuda sintáctica y no garantiza equivalencia funcional de Velocity."
    )


class AdaptRequest(BaseModel):
    internal_id: str


class EditResultRequest(BaseModel):
    subject: str
    body: str
    editor_mode: Literal["visual", "html"] = "html"


class DateTranslationUpdate(BaseModel):
    enabled: bool


class PublicationPrepareRequest(BaseModel):
    connection_id: str


class PublicationBatchPrepareRequest(BaseModel):
    connection_id: str
    internal_ids: list[str]


class PublicationConfirmRequest(BaseModel):
    connection_id: str
    preparation_id: str


class PublicationVerifyRequest(BaseModel):
    connection_id: str
    publication_id: str


class PublicationBatchConfirmRequest(BaseModel):
    connection_id: str
    items: list[dict[str, str]]

