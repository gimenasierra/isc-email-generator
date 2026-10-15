from __future__ import annotations

from app import prompt_rules


def configure_paths(tmp_path, monkeypatch):
    base = tmp_path / "adaptation_rules.md"
    projects = tmp_path / "projects"
    projects.mkdir()
    base.write_text("contrato técnico común", encoding="utf-8")
    monkeypatch.setattr(prompt_rules, "BASE_RULES_FILE", base)
    monkeypatch.setattr(prompt_rules, "PROJECT_RULES_DIR", projects)
    return base, projects


def test_base_contract_and_project_guide_are_independent_and_reload_without_restart(tmp_path, monkeypatch):
    base, _ = configure_paths(tmp_path, monkeypatch)
    rules, path = prompt_rules.load_adaptation_rules()
    assert rules == "contrato técnico común"
    assert path == base

    saved = prompt_rules.save_style_guide("cliente-a", "# Paleta\nAzul", "cliente-a.md")
    assert saved["configured"] is True
    assert saved["filename"] == "cliente-a.md"
    first_hash = saved["hash"]

    updated = prompt_rules.save_style_guide("cliente-a", "# Paleta\nVerde", "reemplazo.md")
    assert updated["content"].endswith("Verde")
    assert updated["hash"] != first_hash
    assert prompt_rules.load_adaptation_rules()[0] == "contrato técnico común"


def test_guides_are_isolated_and_unsafe_project_id_cannot_escape_directory(tmp_path, monkeypatch):
    _, projects = configure_paths(tmp_path, monkeypatch)
    prompt_rules.save_style_guide("cliente-a", "Guía A", "a.md")
    prompt_rules.save_style_guide("cliente-b", "Guía B", "b.md")
    assert prompt_rules.get_style_guide("cliente-a")["content"] == "Guía A"
    assert prompt_rules.get_style_guide("cliente-b")["content"] == "Guía B"

    prompt_rules.save_style_guide("../../fuera", "Segura", "safe.md")
    assert prompt_rules.get_style_guide("../../fuera")["content"] == "Segura"
    assert all(path.parent == projects for path in projects.iterdir())


def test_sanitizer_neutralizes_velocity_and_urls_but_keeps_style_and_policy():
    content = """# Regla\nUsar #0079c1. Política: conservar firma.\n#if($foreign)<a href=\"https://other.example/${url}\">Texto</a>#end"""
    sanitized = prompt_rules.sanitize_style_guide(content)
    assert "$foreign" not in sanitized
    assert "${url}" not in sanitized
    assert "https://other.example" not in sanitized
    assert "#0079c1" in sanitized
    assert "Política: conservar firma" in sanitized
    warnings = prompt_rules.style_guide_warnings(content)
    assert any("variable" in warning for warning in warnings)
    assert any("directiva" in warning for warning in warnings)
    assert any("URL" in warning for warning in warnings)


def test_delete_guide_does_not_affect_other_projects(tmp_path, monkeypatch):
    configure_paths(tmp_path, monkeypatch)
    prompt_rules.save_style_guide("a", "Guía A", "a.md")
    prompt_rules.save_style_guide("b", "Guía B", "b.md")
    assert prompt_rules.delete_style_guide("a")["configured"] is False
    assert prompt_rules.get_style_guide("b")["configured"] is True


def test_default_guide_keeps_visible_product_name_inside_bold_signature_line():
    guide_path = prompt_rules.PROMPTS_DIR / "projects" / "default.md"
    content = guide_path.read_text(encoding="utf-8")

    assert "La mera ubicación dentro de una firma no cuenta como negrita." in content
    assert "línea completa en un único `strong`" in content

    sanitized = prompt_rules.sanitize_style_guide(content)
    assert "La mera ubicación dentro de una firma no cuenta como negrita." in sanitized
    assert "nombre dinámico del producto" in sanitized
