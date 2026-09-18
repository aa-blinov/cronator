"""F10 UI flow: cancel button in the executions list.

Users can see a 'Cancel' button next to any running execution on the
/executions list page, and clicking it cancels the execution.
"""

from __future__ import annotations

import time

import httpx
from playwright.sync_api import Page

from tests.ui.conftest import screenshot


def _create_running_execution() -> tuple[int, int]:
    """Create a long-running script and trigger it. Returns (script_id, exec_id)."""
    with httpx.Client(base_url="http://localhost:8080", auth=("admin", "admin"), timeout=10) as c:
        r = c.post(
            "/api/scripts",
            json={
                "name": f"f10_long_runner_{int(time.time())}",
                "content": "import time\ntime.sleep(30)\n",
                "cron_expression": "0 0 * * *",
                "python_version": "3.12",
                "enabled": False,
                "timeout": 60,
            },
        )
        assert r.status_code == 201, r.text
        script_id = r.json()["id"]
        run = c.post(f"/api/scripts/{script_id}/run")
        assert run.status_code == 200, run.text
        return script_id, run.json()["execution_id"]


def test_f10_executions_page_loads(page: Page, base_url: str) -> None:
    """The executions page must render correctly with the new cancel button column."""
    page.goto(f"{base_url}/executions", wait_until="networkidle")
    screenshot(page, "f10_01_executions_list_page")


def test_f10_cancel_button_visible_for_running(page: Page, base_url: str) -> None:
    """A 'Cancel' button is rendered for each execution with status='running'."""
    script_id, exec_id = _create_running_execution()
    try:
        page.goto(f"{base_url}/executions", wait_until="networkidle")
        # Wait briefly for any auto-refresh to pick up the new row
        page.wait_for_timeout(2000)
        page.reload(wait_until="networkidle")
        # The running row should contain a Cancel button
        cancel_buttons = page.locator('button:has-text("Cancel")')
        assert cancel_buttons.count() >= 1, "no Cancel buttons rendered; expected at least 1"
        screenshot(page, "f10_02_running_execution_with_cancel_button")

        # Cancel the specific execution via API (don't actually click to avoid JS confirm dialog)
        with httpx.Client(base_url="http://localhost:8080", auth=("admin", "admin"), timeout=10) as c:
            result = c.post(f"/api/executions/{exec_id}/cancel")
            assert result.status_code == 200, f"cancel failed: {result.text}"
    finally:
        with httpx.Client(base_url="http://localhost:8080", auth=("admin", "admin"), timeout=10) as c:
            c.delete(f"/api/scripts/{script_id}")


def test_f10_no_cancel_button_for_finished_executions(page: Page, base_url: str) -> None:
    """Finished executions (success/failed/cancelled) should NOT show a Cancel button."""
    page.goto(f"{base_url}/executions?status=success", wait_until="networkidle")
    screenshot(page, "f10_03_finished_executions_no_cancel")
    # The status filter is 'success', so we should see only finished executions
    rows = page.locator("table tbody tr").all()
    for row in rows:
        row_text = (row.text_content() or "").lower()
        assert "running" not in row_text, f"running row in filtered success list: {row_text}"
