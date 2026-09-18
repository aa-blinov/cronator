"""F4 UI flow: verify CHANGELOG.md is rendered in the UI.

We expose /changelog as a simple server-rendered HTML page so users can see
what's changed in each release without leaving the app.
"""

from __future__ import annotations

from playwright.sync_api import Page

from tests.ui.conftest import screenshot


def test_f4_changelog_link_in_footer(page: Page, base_url: str) -> None:
    """The page footer must link to the changelog."""
    page.goto(f"{base_url}/", wait_until="networkidle")
    # Footer should now have a 'Changelog' link
    footer_links = page.locator("footer a, .footer a, body a").all()
    hrefs = [a.get_attribute("href") for a in footer_links]
    assert any(h and "/changelog" in h for h in hrefs), f"no /changelog link in footer; links: {hrefs}"


def test_f4_changelog_page_renders(page: Page, base_url: str) -> None:
    """GET /changelog renders markdown as styled HTML."""
    page.goto(f"{base_url}/changelog", wait_until="networkidle")
    screenshot(page, "f4_01_changelog_top")
    # The rendered page must have at least one h1/h2 heading from the markdown
    heading_count = page.locator("h1, h2").count()
    assert heading_count >= 2, f"expected at least 2 headings, got {heading_count}"
    # "Unreleased" and "0.1.0" sections should both be present
    content = page.content()
    assert "Unreleased" in content, content[:500]
    assert "0.1.0" in content, content[:500]


def test_f4_changelog_mentions_recent_features(page: Page, base_url: str) -> None:
    """The changelog must mention the features we just shipped."""
    page.goto(f"{base_url}/changelog", wait_until="networkidle")
    content = page.content()
    for needle in ("Security headers", "graceful", "health", "Playwright"):
        assert needle in content, f"{needle!r} missing from changelog"
    screenshot(page, "f4_02_changelog_features")
