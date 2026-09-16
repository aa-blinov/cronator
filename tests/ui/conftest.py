"""Shared fixtures and helpers for Playwright UI tests.

Strategy:
- Run against the **real running app** (the docker compose stack at http://localhost:8080).
  This catches visual regressions, network issues, and end-to-end flow problems
  that ASGITransport unit tests miss.
- Authenticate via Basic Auth in the browser context.
- Save screenshots to tests/ui/screenshots/ for visual inspection.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import BrowserContext, Page, sync_playwright

# Make project root importable so we can reuse helpers / config
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("CRONATOR_BASE_URL", "http://localhost:8080")
ADMIN_USER = os.environ.get("CRONATOR_ADMIN_USERNAME", "admin")
ADMIN_PASS = os.environ.get("CRONATOR_ADMIN_PASSWORD", "admin")

SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def screenshot(page: Page, name: str, *, full_page: bool = True) -> Path:
    """Save a screenshot and return its absolute path.

    Names are sanitized and prefixed with a sequence number per test via
    `screenshot_counter` to keep them in execution order.
    """
    safe = name.replace(" ", "_").replace("/", "_")
    out = SCREENSHOTS_DIR / f"{safe}.png"
    page.screenshot(path=str(out), full_page=full_page)
    return out


def http_basic_auth_headers() -> dict[str, str]:
    """Headers for HTTP Basic Auth — used by JS fetch() calls in the browser."""
    import base64

    raw = f"{ADMIN_USER}:{ADMIN_PASS}".encode()
    return {"Authorization": f"Basic {base64.b64encode(raw).decode()}"}


def auth_url(path: str) -> str:
    """Build a URL with HTTP Basic Auth credentials embedded for direct navigation."""
    # Browser will strip credentials from the URL bar after navigation, but they
    # are passed during the initial request.
    if not path.startswith("/"):
        path = "/" + path
    return f"{BASE_URL.replace('://', f'://{ADMIN_USER}:{ADMIN_PASS}@')}{path}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def playwright_instance() -> Generator[Any, None, None]:
    with sync_playwright() as p:
        yield p


@pytest.fixture()
def browser_context(
    playwright_instance: Any,
) -> Generator[BrowserContext, None, None]:
    """A fresh isolated browser context per test (no shared cookies/storage)."""
    context = playwright_instance.chromium.launch(headless=True).new_context(
        viewport={"width": 1440, "height": 900},
        ignore_https_errors=True,
    )
    context.set_extra_http_headers(http_basic_auth_headers())
    yield context
    context.close()


@pytest.fixture()
def page(browser_context: BrowserContext) -> Generator[Page, None, None]:
    """A Page that has Basic Auth credentials in extra headers (sent on every request)."""
    page = browser_context.new_page()
    yield page
    page.close()


@pytest.fixture(autouse=True)
def _wait_for_server(page: Page) -> None:
    """Skip the test cleanly if the app server isn't reachable.

    Lets `pytest tests/ui/ -k something` succeed with "skipped" rather than a
    long stacktrace when the stack is down.
    """
    import urllib.error
    import urllib.request

    try:
        urllib.request.urlopen(BASE_URL + "/health", timeout=2).read()
    except (urllib.error.URLError, ConnectionError, OSError):
        pytest.skip(f"Cronator not reachable at {BASE_URL} — start the stack first")
