"""F1 UI flow: verify security headers are visible in browser devtools-like
context (we can't read response headers in the page DOM, but we can prove
the request to a same-origin endpoint still returns the page).

Captures three screenshots:
1. Page after navigating to / (confirms header middleware didn't break rendering)
2. Page after navigating to /settings (different route, same middleware)
3. Page after navigating to /api/scripts via fetch (JSON view in console — captured via assertions)
"""

from __future__ import annotations

from playwright.sync_api import Page, Response

from tests.ui.conftest import screenshot


def _attach_header_capture(page: Page, captured: dict[str, dict[str, str]]) -> None:
    """Capture all response headers for /api/* and / routes via the response event.

    Playwright's `response.headers` exposes the full response headers including
    those filtered out by the browser's JS fetch API (e.g. X-Frame-Options).
    """
    def on_response(response: Response) -> None:
        try:
            captured[response.url] = dict(response.headers)
        except Exception:
            pass

    page.on("response", on_response)


def _assert_security_headers(headers: dict, label: str) -> None:
    assert headers.get("x-content-type-options") == "nosniff", f"[{label}] {headers}"
    assert headers.get("x-frame-options") == "DENY", f"[{label}] {headers}"
    assert headers.get("referrer-policy") == "strict-origin-when-cross-origin", f"[{label}] {headers}"
    assert "default-src 'self'" in headers.get("content-security-policy", ""), f"[{label}] {headers}"
    assert "camera=()" in headers.get("permissions-policy", ""), f"[{label}] {headers}"


def test_f1_security_headers_dashboard(page: Page, base_url: str) -> None:
    captured: dict[str, dict[str, str]] = {}
    _attach_header_capture(page, captured)
    page.goto(f"{base_url}/", wait_until="networkidle")
    page.wait_for_selector("h1, h2, .navbar", timeout=10_000)
    screenshot(page, "f1_01_dashboard_with_security_headers")
    # Look for the document response (the one matching the navigation URL)
    doc_url = page.url
    doc_headers = captured.get(doc_url, {})
    assert doc_headers, f"no captured response for {doc_url}; captured={list(captured.keys())}"
    _assert_security_headers(doc_headers, f"document {doc_url}")


def test_f1_security_headers_settings(page: Page, base_url: str) -> None:
    captured: dict[str, dict[str, str]] = {}
    _attach_header_capture(page, captured)
    page.goto(f"{base_url}/settings", wait_until="networkidle")
    screenshot(page, "f1_02_settings_with_security_headers")
    doc_url = page.url
    doc_headers = captured.get(doc_url, {})
    _assert_security_headers(doc_headers, f"document {doc_url}")


def test_f1_security_headers_apis_have_headers(page: Page, base_url: str) -> None:
    """Trigger a request to /api/scripts and inspect full response headers via
    Playwright's response event (which sees ALL headers, unlike JS fetch)."""
    captured: dict[str, dict[str, str]] = {}
    _attach_header_capture(page, captured)
    page.goto(f"{base_url}/", wait_until="networkidle")
    # Manually navigate to a URL that issues an API call by clicking dashboard tab
    # Use Playwright's request API to capture a controlled request
    api_response = page.request.get(f"{base_url}/api/scripts")
    screenshot(page, "f1_03_api_responses_have_headers")
    assert api_response.status == 200
    _assert_security_headers(dict(api_response.headers), f"api /api/scripts status={api_response.status}")
