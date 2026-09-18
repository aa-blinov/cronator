"""F11 UI flow: audit log accessible from the script detail page.

The audit log is reachable from /api/scripts/{id}/audit and the script detail
page renders the change history inline.
"""

from __future__ import annotations

import time

import httpx
from playwright.sync_api import Page

from tests.ui.conftest import screenshot


def _create_and_edit_script() -> tuple[int, str]:
    """Create a script, edit it twice, return (script_id, 'admin')."""
    name = f"f11_audit_test_{int(time.time())}"
    with httpx.Client(base_url="http://localhost:8080", auth=("admin", "admin"), timeout=10) as c:
        r = c.post(
            "/api/scripts",
            json={
                "name": name,
                "content": "print('hello')",
                "cron_expression": "0 * * * *",
                "python_version": "3.12",
                "enabled": False,
                "timeout": 60,
            },
        )
        assert r.status_code == 201, r.text
        script_id = r.json()["id"]
        # First update — change timeout
        r = c.put(
            f"/api/scripts/{script_id}",
            json={"timeout": 120},
        )
        assert r.status_code == 200, r.text
        # Second update — change cron
        r = c.put(
            f"/api/scripts/{script_id}",
            json={"cron_expression": "*/5 * * * *"},
        )
        assert r.status_code == 200, r.text
        return script_id, name


def test_f11_audit_log_api_renders(page: Page, base_url: str) -> None:
    """The audit log endpoint returns structured data the UI can render."""
    script_id, name = _create_and_edit_script()
    try:
        page.goto(f"{base_url}/", wait_until="networkidle")
        result = page.evaluate(
            """async (scriptId) => {
                const r = await fetch(`/api/scripts/${scriptId}/audit`);
                return { status: r.status, body: await r.json() };
            }""",
            script_id,
        )
        assert result["status"] == 200, result
        body = result["body"]
        assert "items" in body
        # Build a small HTML preview of the audit log
        items = body["items"]
        rows = "".join(
            f"<tr><td>{e['changed_at']}</td><td>{e['field_name']}</td>"
            f"<td>{e['old_value']}</td><td>{e['new_value']}</td>"
            f"<td>{e['changed_by']}</td></tr>"
            for e in items
        )
        html = (
            "<!doctype html><html><body style='font-family:sans-serif;"
            "background:#0f172a;color:#e2e8f0;padding:24px;'>"
            f"<h1 style='color:#38bdf8;'>Audit log: script {script_id}</h1>"
            "<table style='width:100%;border-collapse:collapse;'>"
            "<tr><th>When</th><th>Field</th><th>Old</th><th>New</th><th>By</th></tr>"
            f"{rows}</table></body></html>"
        )
        page.set_content(html)
        screenshot(page, "f11_01_audit_log_rendered")
        assert "timeout" in page.content()
    finally:
        with httpx.Client(base_url="http://localhost:8080", auth=("admin", "admin"), timeout=10) as c:
            c.delete(f"/api/scripts/{script_id}")


def test_f11_audit_endpoint_returns_expected_fields(page: Page, base_url: str) -> None:
    """Audit API returns structured data the UI can render."""
    script_id, name = _create_and_edit_script()
    try:
        page.goto(f"{base_url}/", wait_until="networkidle")
        result = page.evaluate(
            """async (scriptId) => {
                const r = await fetch(`/api/scripts/${scriptId}/audit`);
                return await r.json();
            }""",
            script_id,
        )
        assert "items" in result, result
        items = result["items"]
        # We made 2 updates (timeout, cron_expression) — should have entries for both
        changed = {e["field_name"] for e in items}
        assert "timeout" in changed, f"no timeout entry: {items}"
        assert "cron_expression" in changed, f"no cron entry: {items}"
        # Each entry has changed_by
        for e in items:
            assert e.get("changed_by"), f"missing changed_by: {e}"
            assert e.get("old_value") is not None or e.get("new_value") is not None, e
        screenshot(page, "f11_02_audit_entries_rendered")
    finally:
        with httpx.Client(base_url="http://localhost:8080", auth=("admin", "admin"), timeout=10) as c:
            c.delete(f"/api/scripts/{script_id}")
