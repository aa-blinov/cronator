"""Baseline screenshots of the existing UI.

Run before implementing features so we can visually diff after changes.
Each screenshot captures the page in its default state (no data fixture)
to act as a regression reference.
"""

from playwright.sync_api import Page

from tests.ui.conftest import screenshot


def test_baseline_dashboard(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/", wait_until="networkidle")
    page.wait_for_selector("h1, h2, .navbar", timeout=10_000)
    screenshot(page, "baseline_dashboard")


def test_baseline_executions(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/executions", wait_until="networkidle")
    screenshot(page, "baseline_executions")


def test_baseline_new_script(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/scripts/new", wait_until="networkidle")
    screenshot(page, "baseline_script_new")


def test_baseline_settings(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/settings", wait_until="networkidle")
    screenshot(page, "baseline_settings")
