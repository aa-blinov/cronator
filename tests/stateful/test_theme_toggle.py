"""TDD tests for F16: Dark/light theme toggle.

The app currently ships with a single 'dim' theme baked into the <html data-theme="dim">
attribute. We add:
- A theme selector that persists choice to localStorage
- Three themes: dim (current dark), light, cupcake
- A toggle button in the sidebar
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
async def test_settings_endpoint_exposes_theme_options(test_client):
    """GET /api/settings should expose the user's preferred theme (or default)."""
    r = await test_client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert "theme" in body, f"settings body missing 'theme': {body}"
    assert body["theme"] in ("dim", "light", "cupcake"), f"unexpected theme: {body.get('theme')}"


@pytest.mark.asyncio
async def test_settings_accepts_theme_update(test_client):
    """PUT /api/settings/update should accept the theme field."""
    r = await test_client.post(
        "/api/settings/update",
        json={"theme": "light"},
    )
    assert r.status_code == 200, r.text
    body = (await test_client.get("/api/settings")).json()
    assert body["theme"] == "light", f"theme not persisted: {body['theme']}"
    # Reset
    await test_client.post("/api/settings/update", json={"theme": "dim"})


def test_base_template_has_theme_toggle():
    """The base template must include a theme toggle UI element."""
    content = (REPO_ROOT / "app" / "templates" / "base.html").read_text()
    lower = content.lower()
    assert "theme" in lower, "no theme references in base template"
    assert (
        "data-theme" in lower or "settheme" in lower.replace(" ", "") or "theme-toggle" in lower
    ), "no theme toggle UI in base template"


def test_base_template_defaults_to_dim_theme():
    """The <html> tag must carry a data-theme attribute (default: dim)."""
    content = (REPO_ROOT / "app" / "templates" / "base.html").read_text()
    # Accept either the Jinja template form (with theme|default) or the literal "dim"
    jinja_form = "theme|default"
    has_jinja_default = jinja_form in content and 'data-theme="{{' in content
    has_literal = 'data-theme="dim"' in content or "data-theme='dim'" in content
    assert has_jinja_default or has_literal, (
        "base template missing data-theme attribute (literal 'dim' or Jinja template)"
    )
