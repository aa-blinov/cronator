"""The script editor must stay light: templates load lazily, not inline.

Baking all 19 built-in templates into the editor page cost every editor
visit ~45KB of mostly unused JSON, inflating it to ~170KB. They now load
from /api/scripts/templates when the picker modal first opens. This test
renders the template the same way the routes do — no client, no server —
and fails if the inline bake or the dead-weight regression comes back.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

REPO_ROOT = Path(__file__).resolve().parents[2]


def _render(script: dict | None) -> str:
    """Render script_editor.html exactly like the page routes do."""
    env = Environment(loader=FileSystemLoader(REPO_ROOT / "app" / "templates"))
    env.filters.setdefault("filesizeformat", lambda v: v)
    template = env.get_template("script_editor.html")
    return template.render(
        request=None,
        page_title="New Script" if script is None else "Edit",
        version="0.0.0",
        theme="dim",
        script=script,
        content="#!/usr/bin/env python3\n",
        python_versions=["3.9", "3.10", "3.11", "3.12", "3.13"],
        is_admin=True,
    )


def test_editor_has_no_inline_templates():
    html = _render(None)
    # The baked-in template sources would repeat these tells per template;
    # the lazy loader only holds the fetch URL.
    assert "api-health-check" not in html, "template JSON is inline again"
    assert "ensureTemplatesLoaded" in html, "lazy template loader missing"


def test_editor_lazy_loader_fetches_right_endpoint():
    html = _render(None)
    assert "/api/scripts/templates" in html, (
        "lazy loader does not point at the real endpoint (it is under the "
        "scripts prefix, not /api/templates)"
    )
    assert "/api/templates'" not in html, (
        "lazy loader hits a dead URL: /api/templates 404s (the endpoint is "
        "/api/scripts/templates)"
    )
