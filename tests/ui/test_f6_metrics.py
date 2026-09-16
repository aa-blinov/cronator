"""F6 UI flow: verify the Prometheus /metrics endpoint in the browser context."""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import Page

from tests.ui.conftest import screenshot


def _render_metrics_in_browser(page: Page, base_url: str) -> str:
    page.goto(f"{base_url}/", wait_until="networkidle")
    text = page.evaluate(
        """async () => {
            const r = await fetch('/metrics');
            return await r.text();
        }"""
    )
    pretty = text.replace("\n", "<br>").replace(" ", "&nbsp;")
    html = (
        "<!doctype html><html><body style='font-family:ui-monospace,Menlo,monospace;"
        "background:#020617;color:#e2e8f0;padding:24px;font-size:11px;'>"
        "<h1 style='color:#38bdf8;'>Cronator /metrics</h1>"
        f"<pre>{pretty}</pre>"
        "</body></html>"
    )
    page.set_content(html)
    return text


def test_f6_metrics_endpoint_returns_text(page: Page, base_url: str) -> None:
    body = _render_metrics_in_browser(page, base_url)
    screenshot(page, "f6_01_metrics_endpoint")
    assert len(body) > 50, f"metrics output too short: {body[:100]}"


def test_f6_metrics_has_app_info(page: Page, base_url: str) -> None:
    body = _render_metrics_in_browser(page, base_url)
    screenshot(page, "f6_02_metrics_app_info")
    assert "crinator_app_info" in body, body[:300]
    assert "version=" in body, body[:300]


def test_f6_metrics_has_running_gauge(page: Page, base_url: str) -> None:
    body = _render_metrics_in_browser(page, base_url)
    assert "crinator_executions_running" in body, body[:300]
    screenshot(page, "f6_03_metrics_running_gauge")


def test_f6_metrics_has_uptime(page: Page, base_url: str) -> None:
    body = _render_metrics_in_browser(page, base_url)
    assert "crinator_uptime_seconds" in body, body[:300]
    screenshot(page, "f6_04_metrics_uptime")
