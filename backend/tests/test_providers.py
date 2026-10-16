from __future__ import annotations

import json

import httpx
import pytest

from app.models import AIConfig, BrandingConfig
from app.providers.base import TemplateContext
from app.providers.mock import MockAdaptationProvider
from app import prompt_rules
from app.providers.remote import AnthropicProvider, GeminiProvider, GroqProvider, OpenAICompatibleProvider, OpenAIProvider, ProviderError, adaptation_prompt, original_has_signature


RESULT = {"subject": "Hola Cliente Nuevo, $name", "body": "<p>#if($name)Hola $name#end</p>", "changes": ["Cliente actualizado"]}
BRANDING = BrandingConfig(old_client_name="Cliente Viejo", new_client_name="Cliente Nuevo")
CONTEXT = TemplateContext(name="Access End Date Modified", key="certification_end_date_modified_notification", locale="en")


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_certificate_failure_has_a_specific_safe_message():
    def handler(request: httpx.Request):
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate in certificate chain", request=request)

    provider = AnthropicProvider(client_for(handler))
    with pytest.raises(ProviderError, match="almacén de confianza de Windows"):
        provider.test_connection(AIConfig(provider="anthropic", model="claude-haiku-4-5-20251001"), "test-key")


@pytest.mark.parametrize("provider_class,provider_id,base_url", [
    (OpenAIProvider, "openai", ""),
    (GroqProvider, "groq", ""),
    (OpenAICompatibleProvider, "openai_compatible", "http://localhost:1234/v1"),
])
def test_openai_compatible_adapters_normalize_output(provider_class, provider_id, base_url):
    def handler(request: httpx.Request):
        payload = json.loads(request.content)
        if provider_id == "openai_compatible":
            assert payload["response_format"]["type"] == "json_schema"
            assert payload["response_format"]["json_schema"]["schema"]["required"] == ["subject", "body", "changes"]
            assert request.extensions["timeout"]["read"] == 300.0
            assert payload["max_tokens"] == 3072
            assert payload["stream"] is False
        else:
            assert payload["response_format"]["type"] == "json_schema"
        if provider_id == "groq":
            assert "include_reasoning" not in payload
            assert "reasoning_effort" not in payload
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(RESULT)}}]})

    provider = provider_class(client_for(handler))
    result = provider.adapt("Hola Cliente Viejo, $name", "<p>#if($name)$name#end</p>", BRANDING, AIConfig(provider=provider_id, model="test-model", base_url=base_url), "secret", CONTEXT)
    assert result.subject == RESULT["subject"]
    assert result.body == RESULT["body"]
    assert result.changes == RESULT["changes"]


def test_gemini_adapter_uses_response_schema():
    def handler(request: httpx.Request):
        if request.method == "GET":
            return httpx.Response(200, json={"outputTokenLimit": 16384})
        payload = json.loads(request.content)
        assert request.headers["x-goog-api-key"] == "secret"
        assert payload["generationConfig"]["responseMimeType"] == "application/json"
        assert payload["generationConfig"]["maxOutputTokens"] == 16384
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(RESULT)}]}}]})

    provider = GeminiProvider(client_for(handler))
    result = provider.adapt("Viejo", "<p>$name</p>", BRANDING, AIConfig(provider="gemini", model="gemini-test"), "secret", CONTEXT)
    assert result.body == RESULT["body"]


def test_gemini_caps_adaptation_output_at_32k():
    def handler(request: httpx.Request):
        if request.method == "GET":
            return httpx.Response(200, json={"outputTokenLimit": 65536})
        payload = json.loads(request.content)
        assert payload["generationConfig"]["maxOutputTokens"] == 32768
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(RESULT)}]}}]})

    provider = GeminiProvider(client_for(handler))
    result = provider.adapt("Viejo", "<p>$name</p>", BRANDING, AIConfig(provider="gemini", model="gemini-test"), "secret", CONTEXT)
    assert result.subject == RESULT["subject"]


def test_gemini_reports_max_tokens_as_truncation():
    def handler(request: httpx.Request):
        if request.method == "GET":
            return httpx.Response(200, json={"outputTokenLimit": 8192})
        return httpx.Response(200, json={
            "candidates": [{
                "finishReason": "MAX_TOKENS",
                "content": {"parts": [{"text": '{"subject":"parcial"'}]},
            }],
        })

    provider = GeminiProvider(client_for(handler))
    with pytest.raises(ProviderError, match="adaptación truncada"):
        provider.adapt("Viejo", "<p>$name</p>", BRANDING, AIConfig(provider="gemini", model="gemini-test"), "secret", CONTEXT)


def test_anthropic_adapter_uses_current_structured_output_shape():
    def handler(request: httpx.Request):
        payload = json.loads(request.content)
        assert payload["output_config"]["format"]["type"] == "json_schema"
        assert payload["output_config"]["effort"] == "low"
        assert payload["max_tokens"] == 16384
        assert request.headers["x-api-key"] == "secret"
        return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(RESULT)}]})

    provider = AnthropicProvider(client_for(handler))
    result = provider.adapt("Viejo", "<p>$name</p>", BRANDING, AIConfig(provider="anthropic", model="claude-test"), "secret", CONTEXT)
    assert result.subject == RESULT["subject"]


def test_anthropic_connection_allows_room_for_final_text():
    def handler(request: httpx.Request):
        payload = json.loads(request.content)
        assert payload["max_tokens"] == 64
        assert "output_config" not in payload
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "OK"}], "stop_reason": "end_turn"},
        )

    result = AnthropicProvider(client_for(handler)).test_connection(
        AIConfig(provider="anthropic", model="claude-haiku-5-5"),
        "secret",
    )
    assert "Conexión correcta" in result.message


def test_anthropic_unstructured_fallback_keeps_adaptation_token_budget():
    calls = 0

    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        payload = json.loads(request.content)
        assert payload["max_tokens"] == 16384
        if calls == 1:
            assert "output_config" in payload
            return httpx.Response(400, json={"error": {"message": "structured output unavailable"}})
        assert "output_config" not in payload
        return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(RESULT)}]})

    result = AnthropicProvider(client_for(handler)).adapt(
        "Viejo",
        "<p>$name</p>",
        BRANDING,
        AIConfig(provider="anthropic", model="claude-haiku-5-5"),
        "secret",
        CONTEXT,
    )
    assert calls == 2
    assert result.subject == RESULT["subject"]


def test_anthropic_reports_token_truncation_without_exposing_content():
    provider = AnthropicProvider(
        client_for(
            lambda _: httpx.Response(
                200,
                json={"content": [{"type": "thinking", "thinking": "private"}], "stop_reason": "max_tokens"},
            )
        )
    )

    with pytest.raises(ProviderError, match="alcanzó el límite de tokens") as error:
        provider.test_connection(AIConfig(provider="anthropic", model="claude-haiku-5-5"), "secret")
    assert "private" not in str(error.value)


def test_simulated_adapter_never_needs_credentials():
    result = MockAdaptationProvider().adapt("Cliente Viejo $name", "<p>Cliente Viejo</p>", BRANDING, AIConfig(), "", CONTEXT)
    assert result.subject == "Cliente Nuevo $name"
    assert result.body == "<p>Cliente Nuevo</p>"


def test_ai_prompt_allows_inferred_colors_with_clear_guidance():
    config = BrandingConfig(color_instructions="Usar violeta como color principal")
    prompt = adaptation_prompt("Asunto", "<p style='color:#000'>$name</p>", config, CONTEXT)
    assert '"Indicaciones de color": "Usar violeta como color principal"' in prompt
    assert "Los mapeos exactos tienen prioridad" in prompt


def test_ai_prompt_forbids_markdown_and_field_name_placeholders():
    prompt = adaptation_prompt("Asunto", "<p>$name</p>", BRANDING, CONTEXT)
    assert "Devolver exclusivamente un objeto JSON válido" in prompt
    assert "La plantilla original es la única fuente autorizada" in prompt
    assert "Reemplazo literal del logo; nunca es Velocity" in prompt
    assert "new_logo_url" not in prompt


def test_ai_prompt_freezes_subject_and_body_velocity_branches_separately():
    subject = "#if (${source})Source ${token}#else Default ${token}#end"
    body = "<p>#if (${source})${source}#else${PRODUCT_NAME}#end</p>"

    prompt = adaptation_prompt(subject, body, BrandingConfig(target_language="Español"), CONTEXT)

    assert '"subject_directives_ordered_verbatim": ["#if (${source})", "#else", "#end"]' in prompt
    assert '"body_directives_ordered_verbatim": ["#if (${source})", "#else", "#end"]' in prompt
    assert "No simplifiques un asunto condicional" in prompt
    assert "secuencias inmutables por campo" in prompt


def test_ai_prompt_never_treats_product_name_as_a_client_literal():
    body = "<p>${PRODUCT_NAME}</p><p>The ${PRODUCT_NAME} Team</p>"

    prompt = adaptation_prompt(
        "Password Reset",
        body,
        BrandingConfig(new_client_name="Assertiva", product_display_name="Assertiva"),
        CONTEXT,
    )

    assert "`${PRODUCT_NAME}` es un valor dinámico de ISC" in prompt
    assert "no es sinónimo del cliente anterior, cliente nuevo, nombre visible del producto, firma ni footer" in prompt
    assert '"velocity_variable_counts_original_minimum": {"${PRODUCT_NAME}": 2}' in prompt


def test_ai_prompt_preserves_formal_directives_and_variable_brace_notation():
    prompt = adaptation_prompt(
        "#if($approved)A#{else}B#end",
        "<p>$reviewerComment</p>",
        BrandingConfig(target_language="Español"),
        CONTEXT,
    )

    assert '"subject_directives_ordered_verbatim": ["#if($approved)", "#{else}", "#end"]' in prompt
    assert '"body_velocity_references_ordered_verbatim": ["$reviewerComment"]' in prompt
    assert "No conviertas `$nombre` en `${nombre}`" in prompt
    assert "Nunca agregues ni retires llaves de una directiva" in prompt


def test_invalid_provider_json_has_clear_error():
    provider = OpenAICompatibleProvider(client_for(lambda _: httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]})))
    with pytest.raises(ProviderError, match="subject, body y changes"):
        provider.adapt("A", "B", BRANDING, AIConfig(provider="openai_compatible", model="local", base_url="http://localhost:1234/v1"), "", CONTEXT)


def test_local_openai_base_url_adds_v1_automatically():
    settings = AIConfig(provider="openai_compatible", model="local", base_url="http://127.0.0.1:1234")
    assert settings.base_url == "http://127.0.0.1:1234/v1"


def test_remote_provider_discards_stale_local_base_url():
    settings = AIConfig(provider="groq", model="openai/gpt-oss-120b", base_url="http://127.0.0.1:1234/v1")
    assert settings.base_url == ""


def test_groq_always_uses_official_api_even_with_legacy_local_url():
    def handler(request: httpx.Request):
        assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(RESULT)}}]})

    legacy_settings = AIConfig.model_construct(
        provider="groq",
        model="openai/gpt-oss-120b",
        base_url="http://127.0.0.1:1234/v1",
    )
    result = GroqProvider(client_for(handler)).adapt("Viejo", "<p>$name</p>", BRANDING, legacy_settings, "secret", CONTEXT)
    assert result.subject == RESULT["subject"]


def test_groq_gpt_oss_connection_reserves_tokens_for_final_content():
    def handler(request: httpx.Request):
        payload = json.loads(request.content)
        assert payload["model"] == "openai/gpt-oss-120b"
        assert payload["include_reasoning"] is False
        assert payload["reasoning_effort"] == "low"
        assert payload["max_tokens"] == 64
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    result = GroqProvider(client_for(handler)).test_connection(
        AIConfig(provider="groq", model="openai/gpt-oss-120b"),
        "secret",
    )
    assert "Conexión correcta" in result.message


@pytest.mark.parametrize("base_url", [
    "http://127.0.0.1:1234/api/v1",
    "http://127.0.0.1:1234/v1/chat/completions",
])
def test_local_openai_base_url_rejects_wrong_endpoint_shapes(base_url):
    with pytest.raises(ValueError, match="OpenAI-compatible|URL base"):
        AIConfig(provider="openai_compatible", model="local", base_url=base_url)


def test_local_provider_explains_non_openai_compatible_response():
    provider = OpenAICompatibleProvider(client_for(lambda _: httpx.Response(200, json={"output": [{"content": "OK"}]})))
    with pytest.raises(ProviderError, match="OpenAI-compatible.*127.0.0.1:1234/v1"):
        provider.test_connection(
            AIConfig(provider="openai_compatible", model="local", base_url="http://127.0.0.1:1234/v1"),
            "",
        )


def test_local_provider_has_extended_timeout_with_specific_error():
    def handler(request: httpx.Request):
        raise httpx.ReadTimeout("slow local model", request=request)

    provider = OpenAICompatibleProvider(client_for(handler))
    with pytest.raises(ProviderError, match="5 minutos"):
        provider.test_connection(
            AIConfig(provider="openai_compatible", model="local", base_url="http://127.0.0.1:1234/v1"),
            "",
        )


def test_local_engine_failure_is_not_retried_and_has_actionable_error():
    calls = 0

    def handler(_: httpx.Request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            400,
            json={"error": {"message": "Engine protocol predict request failed: fetch failed"}},
        )

    provider = OpenAICompatibleProvider(client_for(handler))
    with pytest.raises(ProviderError) as error:
        provider.adapt(
            "Asunto",
            "<p>Cuerpo</p>",
            BrandingConfig(),
            AIConfig(provider="openai_compatible", model="qwen3.5-9b", base_url="http://127.0.0.1:1234/v1"),
            "",
            CONTEXT,
        )

    assert calls == 1
    assert "perdió la comunicación con el motor de inferencia" in str(error.value)
    assert "Max Concurrent Predictions = 1" in str(error.value)


def test_prompt_sets_language_guide_mode_and_missing_title_context():
    config = BrandingConfig(
        target_language="Español neutro",
        generate_missing_title=True,
        mode="guide",
    )
    prompt = adaptation_prompt("Access End Date Modified", "<p>Dear $name</p>", config, CONTEXT)
    assert '"Idioma de destino": "Español neutro"' in prompt
    assert '"Nombre": "Access End Date Modified"' in prompt
    assert '"key": "certification_end_date_modified_notification"' in prompt
    assert "GUÍA MARKDOWN DEL PROYECTO" in prompt
    assert "derivarlo del nombre de la plantilla" in prompt
    assert "modificar únicamente texto visible" in prompt
    assert "reference_html" not in prompt


def test_guide_velocity_and_urls_are_neutralized_before_reaching_provider(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(prompt_rules, "PROJECT_RULES_DIR", projects)
    guide = '<div style="color:#c83298">#if($foreign)<a href="https://foreign.example/${foreignUrl}">Política visible</a>#end</div>'
    prompt_rules.save_style_guide("default", guide, "guide.md")
    prompt = adaptation_prompt("Asunto $allowed", "<p>$allowed</p>", BrandingConfig(mode="guide"), CONTEXT)
    assert "$foreign" not in prompt
    assert "${foreignUrl}" not in prompt
    assert "https://foreign.example" not in prompt
    assert "[DIRECTIVA_VELOCITY_DE_EJEMPLO_NEUTRALIZADA]" in prompt
    assert "[URL_DE_EJEMPLO_RETIRADA]" in prompt
    assert "Política visible" in prompt
    assert "color:#c83298" in prompt
    assert '"velocity_variable_counts_original_minimum": {"$allowed": 2}' in prompt


def test_preserve_mode_does_not_include_project_guide():
    prompt = adaptation_prompt("Asunto original", "<p>Contenido original</p>", BrandingConfig(mode="preserve"), CONTEXT)
    assert "GUÍA MARKDOWN DEL PROYECTO" not in prompt
    assert "Contenido original" in prompt


def test_existing_signature_suppresses_configured_fallback_in_prompt():
    config = BrandingConfig(signature="Saludos, Equipo nuevo")
    body = "<p>Contenido</p><p>Thanks,<br>The ${__global.productName} Team</p>"
    prompt = adaptation_prompt("Asunto", body, config, CONTEXT)
    assert original_has_signature(body, config.signature) is True
    assert '"La plantilla original ya tiene firma": true' in prompt
    assert '"Firma de respaldo solamente": ""' in prompt
    assert '"${__global.productName}": 1' in prompt
    assert "como mínimo, sus cantidades" in prompt


def test_explicit_configuration_precedes_guide():
    prompt = adaptation_prompt("Asunto", "<a href='$url'>Abrir</a>", BrandingConfig(mode="guide", signature="Firma explícita"), CONTEXT)
    assert "Campos explícitos de configuración" in prompt
    assert '"Firma de respaldo solamente": "Firma explícita"' in prompt
    assert '"$url": 1' in prompt


def test_problematic_velocity_references_are_inventoried_and_guide_cannot_authorize_them(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(prompt_rules, "PROJECT_RULES_DIR", projects)
    prompt_rules.save_style_guide(
        "default",
        "Ejemplos no autorizados: ${__global.productName}, $__global.productUrl y $approverPath.",
        "guide.md",
    )
    original = "<p>${__global.productName}</p><a href='$__global.productUrl/ui/d/$approverPath'>Abrir</a>"
    prompt = adaptation_prompt("Aviso ${__global.productName}", original, BrandingConfig(mode="guide"), CONTEXT)
    assert '"${__global.productName}": 2' in prompt
    assert '"$__global.productUrl": 1' in prompt
    assert '"$approverPath": 1' in prompt
    guide_section = prompt.split("GUÍA MARKDOWN DEL PROYECTO", 1)[1].split("ASUNTO ORIGINAL", 1)[0]
    assert "${__global.productName}" not in guide_section
    assert "$__global.productUrl" not in guide_section
    assert "$approverPath" not in guide_section
    assert "Podés repetir una variable existente" in prompt
    assert "No inventes rutas, destinos, condiciones ni variables" in prompt


def test_prompt_allows_button_and_fallback_with_existing_variables():
    body = "<p>Revisá la solicitud en $__global.productUrl/ui/d/$approverPath.</p>"
    prompt = adaptation_prompt("Recordatorio", body, BrandingConfig(mode="preserve"), CONTEXT)
    assert '"allowed_velocity_references_closed_set": ["$__global.productUrl", "$approverPath"]' in prompt
    assert '"$__global.productUrl": 1' in prompt
    assert '"$approverPath": 1' in prompt
    assert "Podés repetir una variable existente solamente para presentar el mismo valor o URL en un botón y en su fallback" in prompt


def test_prompt_marks_logo_configuration_as_literal_not_velocity():
    config = BrandingConfig(
        old_logo_url="https://old.example/logo.png",
        new_logo_url="https://new.example/logo.png",
    )
    prompt = adaptation_prompt("Asunto", '<img src="https://old.example/logo.png">', config, CONTEXT)
    assert '"Reemplazo literal del logo; nunca es Velocity"' in prompt
    assert '"URL literal original": "https://old.example/logo.png"' in prompt
    assert '"URL literal de destino": "https://new.example/logo.png"' in prompt
    assert "new_logo_url" not in prompt
    assert "copiá ese valor literal" in prompt


def test_assertiva_guide_centers_button_and_fallback_message():
    prompt = adaptation_prompt(
        "Recordatorio",
        "<p>Revisá la solicitud en $registrationUrl.</p>",
        BrandingConfig(mode="guide"),
        CONTEXT,
    )
    guide_section = prompt.split("GUÍA MARKDOWN DEL PROYECTO", 1)[1].split("ASUNTO ORIGINAL", 1)[0]
    assert "contenedor `text-align:center; margin:30px 0`" in guide_section
    assert "inmediatamente debajo, centrado" in guide_section
    assert "reemplazar ese fragmento por un único CTA" in guide_section
    assert "No dejar otro enlace independiente arriba" in guide_section
    assert "El destino solo queda visible en el respaldo" in guide_section
    assert "tanto `href` como texto visible deben copiar exactamente la misma expresión de destino original" in guide_section
    assert "$registrationUrl" not in guide_section


def test_assertiva_guide_translates_title_and_bolds_only_visible_velocity_values():
    prompt = adaptation_prompt(
        "Password Reset",
        "<p>Dear ${user.name}</p><a href='${verificationURL}'>Open</a>",
        BrandingConfig(mode="guide", target_language="Español neutro", generate_missing_title=True),
        CONTEXT,
    )
    guide_section = prompt.split("GUÍA MARKDOWN DEL PROYECTO", 1)[1].split("ASUNTO ORIGINAL", 1)[0]
    assert "Usar español neutro, claro y profesional cuando sea el idioma configurado" in guide_section
    assert "si el original es una frase nominal, traducirlo como frase nominal" in guide_section
    assert "preferentemente en 2–6 palabras" in guide_section
    assert "envolver únicamente cada referencia Velocity que representa un dato con un solo `strong`" in guide_section
    assert "incluidas las ramas condicionales" in guide_section
    assert "atributos (`href`, `src`, `style`)" in guide_section
    assert "El enlace visible de respaldo conserva su estilo de enlace, no negrita" in guide_section
    assert "firma" in guide_section
    assert "envolver la expresión completa en un solo `strong`" in guide_section
    assert "nunca destacar solo una parte" in guide_section
    assert "${user.name}" not in guide_section
    assert "${verificationURL}" not in guide_section


def test_assertiva_guide_contains_neutral_reusable_components_without_foreign_business_data():
    prompt = adaptation_prompt("Aviso", "<p>$value</p>", BrandingConfig(mode="guide"), CONTEXT)
    guide_section = prompt.split("GUÍA MARKDOWN DEL PROYECTO", 1)[1].split("ASUNTO ORIGINAL", 1)[0]
    assert "Código, token o identificador central" in guide_section
    assert "Información y estados" in guide_section
    assert "Nota de seguridad o soporte" in guide_section
    assert "Listas y comentarios" in guide_section
    assert "#28a745" in guide_section
    assert "#d9534f" in guide_section
    assert "#fff9e6" in guide_section
    assert "0 2px 4px rgba( 0 , 0 , 0 , 0.1 )" in guide_section
    assert "administraciondeaccesos" not in guide_section.casefold()
    assert "bupa" not in guide_section.casefold()
    assert "identitynow.com" not in guide_section.casefold()
    assert "$value" not in guide_section


def test_assertiva_guide_requires_status_and_scheduled_date_boxes():
    prompt = adaptation_prompt("Estado", "<p>Resultado y fechas originales</p>", BrandingConfig(mode="guide"), CONTEXT)
    guide_section = prompt.split("GUÍA MARKDOWN DEL PROYECTO", 1)[1].split("ASUNTO ORIGINAL", 1)[0]

    assert "Estos bloques son obligatorios" in guide_section
    assert "Resultado aprobado o exitoso: bloque de éxito verde" in guide_section
    assert "Resultado denegado, rechazado o fallido: bloque de error rojo" in guide_section
    assert "Fecha programada de inicio o activación: bloque informativo azul" in guide_section
    assert "Fecha programada de finalización, remoción o vencimiento: bloque de advertencia amarillo" in guide_section
    assert "Mantener el bloque dentro de la misma rama condicional del original" in guide_section
