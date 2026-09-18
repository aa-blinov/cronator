"""F3 UI flow: verify the running app responds normally before and after a
graceful restart.

SIGTERM-triggered shutdown can't be observed from inside the browser, so we
exercise the lifecycle by:
1. Verifying the dashboard still renders after F3 changes
2. Verifying /health still works
3. Optional: stop the stack and confirm graceful_shutdown logs the cancellation
"""

from __future__ import annotations

import json

from playwright.sync_api import Page

from tests.ui.conftest import screenshot


def test_f3_dashboard_still_loads_after_restart(page: Page, base_url: str) -> None:
    """Sanity: after F3 changes are deployed, the dashboard still renders normally."""
    page.goto(f"{base_url}/", wait_until="networkidle")
    page.wait_for_selector("h1, h2, .navbar", timeout=10_000)
    screenshot(page, "f3_01_dashboard_after_graceful_shutdown_changes")


def test_f3_health_still_reports_cleanly(page: Page, base_url: str) -> None:
    """/health must still work after the graceful_shutdown refactor."""
    page.goto(f"{base_url}/", wait_until="networkidle")  # establish origin
    body = page.evaluate(
        """async () => {
            const r = await fetch('/health');
            return await r.json();
        }"""
    )
    pretty = json.dumps(body, indent=2)
    html = (
        "<!doctype html><html><body style='font-family:ui-monospace,Menlo,monospace;"
        "background:#0f172a;color:#e2e8f0;padding:24px;'>"
        "<h1 style='color:#38bdf8;'>Health after F3 graceful-shutdown changes</h1>"
        f"<pre>{pretty}</pre>"
        "</body></html>"
    )
    page.set_content(html)
    screenshot(page, "f3_02_health_after_graceful_shutdown")
    assert "status" in body, body
    assert "components" in body, body
    assert "scheduler" in body["components"], body


def test_f3_executions_page_still_loads(page: Page, base_url: str) -> None:
    """The executions page (which lists the result of past runs) must still render."""
    page.goto(f"{base_url}/executions", wait_until="networkidle")
    screenshot(page, "f3_03_executions_page_after_changes")
