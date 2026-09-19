"""F2 UI flow: extended /health endpoint.

Screenshots are HTML-rendered JSON of the /health response, captured via the
browser DevTools-like inspect pattern. We can't take a "real" screenshot of a
JSON endpoint, but we can render the JSON in a styled HTML view to confirm
operators can read it visually.
"""

from __future__ import annotations

import json

from playwright.sync_api import Page

from tests.ui.conftest import screenshot


def _render_health_json_in_browser(page: Page, base_url: str) -> dict:
    """Navigate to a synthetic HTML page that displays the /health JSON nicely.

    Returns the parsed JSON for additional assertions."""
    page.goto(f"{base_url}/", wait_until="networkidle")
    json_str = page.evaluate(
        """async () => {
            const r = await fetch('/health');
            return await r.text();
        }"""
    )
    body = json.loads(json_str)
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Health response</title>"
        "<style>"
        "body{font-family:ui-monospace,Menlo,monospace;background:#0f172a;color:#e2e8f0;"
        "padding:24px;margin:0;}"
        "h1{color:#38bdf8;font-size:18px;margin-bottom:16px;}"
        ".status{font-weight:700;font-size:24px;}"
        ".healthy{color:#22c55e;} .degraded{color:#f59e0b;} .unhealthy{color:#ef4444;}"
        "table{width:100%;border-collapse:collapse;margin-top:16px;}"
        "th,td{text-align:left;padding:6px 12px;border:1px solid #334155;}"
        "th{background:#1e293b;}"
        "pre{background:#020617;padding:16px;border-radius:8px;overflow:auto;}"
        "</style></head><body>"
        "<h1>Cronator /health (live response)</h1>"
        f'<div class="status {body.get("status", "")}">{body.get("status", "?").upper()}</div>'
        f"<div>version: <code>{body.get('version', '?')}</code> &middot; "
        f"app: <code>{body.get('app', '?')}</code></div>"
        "<h2 style='color:#94a3b8;font-size:14px;margin-top:20px;'>Components</h2>"
        "<table><thead><tr><th>Component</th><th>Status / Details</th></tr></thead><tbody>"
    )
    for name, info in body.get("components", {}).items():
        html += f"<tr><td>{name}</td><td><pre>{json.dumps(info, indent=2)}</pre></td></tr>"
    html += "</tbody></table></body></html>"
    page.set_content(html)
    return body


def test_f2_health_dashboard(page: Page, base_url: str) -> None:
    body = _render_health_json_in_browser(page, base_url)
    screenshot(page, "f2_01_health_overview")
    # Structural assertions: every required key from F2 backend tests
    assert body["status"] in ("healthy", "degraded"), body
    assert "version" in body, body
    assert "components" in body, body
    assert "database" in body["components"], body
    assert "scheduler" in body["components"], body
    assert "disk" in body["components"], body
    assert "migrations" in body["components"], body


def test_f2_health_disk_section(page: Page, base_url: str) -> None:
    body = _render_health_json_in_browser(page, base_url)
    screenshot(page, "f2_02_health_disk_section")
    disk = body["components"]["disk"]
    assert "free_mb" in disk, disk
    assert "total_mb" in disk, disk
    assert "used_percent" in disk, disk
    # Show the disk stats in a smaller, more focused view
    focused_html = (
        "<!doctype html><html><body style='font-family:sans-serif;background:#0f172a;"
        "color:#e2e8f0;padding:24px;'>"
        "<h1 style='color:#38bdf8;'>Disk Usage</h1>"
        "<table style='border-collapse:collapse;width:100%;'>"
        "<tr><td>Total</td><td><b>" + f"{disk.get('total_mb', '?')} MB" + "</b></td></tr>"
        "<tr><td>Free</td><td><b>" + f"{disk.get('free_mb', '?')} MB" + "</b></td></tr>"
        "<tr><td>Used</td><td><b>" + f"{disk.get('used_percent', '?')}%" + "</b></td></tr>"
        "</table></body></html>"
    )
    page.set_content(focused_html)
    screenshot(page, "f2_03_health_disk_focus")


def test_f2_health_scheduler_section(page: Page, base_url: str) -> None:
    body = _render_health_json_in_browser(page, base_url)
    screenshot(page, "f2_04_health_scheduler_section")
    scheduler = body["components"]["scheduler"]
    assert scheduler.get("status") in ("running", "stopped"), scheduler
    assert "job_count" in scheduler, scheduler
    assert isinstance(scheduler["job_count"], int), scheduler
