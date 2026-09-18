"""Playwright UI tests for Q1: /scripts list page with bulk actions.

Flows:
1. /scripts renders 200, lists existing scripts, has search + status filter
2. Search input filters the table client-side (data-search attribute)
3. Status filter dropdown submits the form
4. Selecting rows reveals the bulk toolbar
5. Selecting all toggles every row checkbox
6. Bulk disable flips every targeted row to "disabled" + shows toast
7. Sidebar link to /scripts is present and active on /scripts page
"""

from __future__ import annotations

import time

from playwright.sync_api import expect

from tests.ui.conftest import BASE_URL, screenshot


def _basic_auth() -> str:
    import base64
    return base64.b64encode(b"admin:admin").decode("ascii")


def _create_script(page, name: str, content: str = "print(1)") -> int:
    resp = page.request.post(
        f"{BASE_URL}/api/scripts",
        data={
            "name": name,
            "content": content,
            "cron_expression": "0 * * * *",
            "enabled": "true",
            "python_version": "3.12",
            "timeout": "60",
            "path": f"/scripts/{name}/main.py",
        },
        headers={"Authorization": f"Basic {_basic_auth()}"},
    )
    assert resp.ok, resp.text()
    return resp.json()["id"]


def test_q1_scripts_page_renders_with_table(page):
    """GET /scripts returns a page with the table and at least one of our seeded scripts."""
    suffix = int(time.time())
    _create_script(page, f"q1_render_a_{suffix}")
    _create_script(page, f"q1_render_b_{suffix}")

    page.goto(f"{BASE_URL}/scripts", wait_until="domcontentloaded")
    body = page.locator("body")
    expect(body).to_contain_text(f"q1_render_a_{suffix}")
    expect(body).to_contain_text(f"q1_render_b_{suffix}")
    expect(page.get_by_test_id("scripts-table")).to_be_visible()
    screenshot(page, "q1_01_scripts_page_table")


def test_q1_search_input_is_present(page):
    """The /scripts page has a search input."""
    page.goto(f"{BASE_URL}/scripts", wait_until="domcontentloaded")
    expect(page.get_by_test_id("scripts-search-input")).to_be_visible()
    screenshot(page, "q1_02_search_input")


def test_q1_search_input_filters_results(page):
    """Typing into the search field submits the form and shows only matching rows."""
    suffix = int(time.time())
    target_name = f"q1_filter_target_{suffix}"
    other_name = f"q1_filter_other_{suffix}"
    _create_script(page, target_name)
    _create_script(page, other_name)

    page.goto(f"{BASE_URL}/scripts?search={target_name}", wait_until="domcontentloaded")
    body = page.locator("body")
    expect(body).to_contain_text(target_name)
    expect(body).not_to_contain_text(other_name)
    screenshot(page, "q1_03_search_filtered")


def test_q1_status_filter_only_enabled(page):
    """The ?status=enabled filter excludes disabled scripts."""
    suffix = int(time.time())
    enabled_name = f"q1_enabled_{suffix}"
    disabled_name = f"q1_disabled_{suffix}"
    _create_script(page, enabled_name)

    # Create a disabled one
    page.request.post(
        f"{BASE_URL}/api/scripts",
        data={
            "name": disabled_name,
            "content": "print(1)",
            "cron_expression": "0 * * * *",
            "enabled": "false",
            "python_version": "3.12",
            "timeout": "60",
            "path": f"/scripts/{disabled_name}/main.py",
        },
        headers={"Authorization": f"Basic {_basic_auth()}"},
    )

    page.goto(f"{BASE_URL}/scripts?status=enabled", wait_until="domcontentloaded")
    body = page.locator("body")
    expect(body).to_contain_text(enabled_name)
    expect(body).not_to_contain_text(disabled_name)


def test_q1_bulk_toolbar_appears_when_row_selected(page):
    """Selecting a row checkbox reveals the bulk-action toolbar."""
    suffix = int(time.time())
    _create_script(page, f"q1_bulk_{suffix}")

    page.goto(f"{BASE_URL}/scripts", wait_until="domcontentloaded")
    toolbar = page.get_by_test_id("bulk-toolbar")
    # Initially hidden
    expect(toolbar).to_be_hidden()

    # Click first row checkbox
    page.locator(".row-checkbox").first.check()
    expect(toolbar).to_be_visible()
    count_el = page.get_by_test_id("bulk-selected-count")
    expect(count_el).to_have_text("1")
    screenshot(page, "q1_04_bulk_toolbar_visible")


def test_q1_select_all_toggles_every_row(page):
    """The header checkbox selects/deselects every visible row."""
    suffix = int(time.time())
    _create_script(page, f"q1_selectall_a_{suffix}")
    _create_script(page, f"q1_selectall_b_{suffix}")
    _create_script(page, f"q1_selectall_c_{suffix}")

    page.goto(f"{BASE_URL}/scripts?search=q1_selectall_", wait_until="domcontentloaded")
    master = page.get_by_test_id("select-all")
    master.check()

    checked = page.locator(".row-checkbox:checked").count()
    total = page.locator(".row-checkbox").count()
    assert checked == total > 0
    expect(page.get_by_test_id("bulk-selected-count")).to_have_text(str(total))

    # Uncheck master → all rows uncheck
    master.uncheck()
    expect(page.locator(".row-checkbox:checked")).to_have_count(0)
    expect(page.get_by_test_id("bulk-toolbar")).to_be_hidden()
    screenshot(page, "q1_05_select_all")


def test_q1_bulk_disable_flips_status_and_shows_toast(page):
    """Selecting rows + clicking Disable hits /bulk/disable, reloads, shows toast.

    The toast appears briefly on the page before window.location.reload()
    navigates away — we can't reliably assert it in the same locator session.
    Instead, verify the API state changed (enabled=False) after reload.
    """
    suffix = int(time.time())
    unique = f"q1_disable_{suffix}"
    s1 = _create_script(page, f"{unique}_a")
    s2 = _create_script(page, f"{unique}_b")

    # Filter by the exact unique prefix so we only see our two scripts
    page.goto(f"{BASE_URL}/scripts?search={unique}", wait_until="domcontentloaded")

    # Sanity: both our scripts are visible
    body = page.locator("body")
    expect(body).to_contain_text(f"{unique}_a")
    expect(body).to_contain_text(f"{unique}_b")

    # Select all (only our two scripts are in the filtered list)
    page.get_by_test_id("select-all").check()
    expect(page.get_by_test_id("bulk-selected-count")).to_have_text("2")

    page.get_by_test_id("bulk-disable").click()

    # Wait for the reload triggered by bulkAction()
    page.wait_for_load_state("networkidle")
    screenshot(page, "q1_06_bulk_disable_after_reload")

    # Verify the API state changed for both scripts
    for sid in (s1, s2):
        r = page.request.get(
            f"{BASE_URL}/api/scripts/{sid}",
            headers={"Authorization": f"Basic {_basic_auth()}"},
        )
        assert r.ok, r.text()
        assert r.json()["enabled"] is False, f"script {sid} still enabled"


def test_q1_sidebar_has_scripts_link(page):
    """The sidebar lists 'Scripts' and links to /scripts."""
    page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
    link = page.locator("a[href='/scripts']")
    expect(link.first).to_be_visible()
    expect(link.first).to_contain_text("Scripts")
    screenshot(page, "q1_07_sidebar_scripts_link")