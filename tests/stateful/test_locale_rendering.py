"""The stored locale now changes the words on the page.

The setting existed since F15 with nothing reading it. These tests pin the
contract end to end: the API accepts ru, every server-rendered page answers
in Russian, and the English default keeps every existing assertion working.
"""

from __future__ import annotations

import pytest

from app.services.settings_service import settings_service


@pytest.fixture(autouse=True)
def _reset_locale_cache():
    """The settings singleton is shared across the test process; a locale
    set here must not leak into other pages' rendering."""
    settings_service._cache.pop("locale", None)
    yield
    settings_service._cache.pop("locale", None)


async def test_dashboard_renders_in_russian(test_client, script_factory, execution_factory):
    from datetime import UTC, datetime

    from app.models.execution import ExecutionStatus

    await test_client.post("/api/locale", json={"locale": "ru"})

    # A failing run makes the "Requires Attention" section render, so its
    # heading can be asserted too.
    script = await script_factory(name="ru_dash_script", content="print(1)", enabled=True)
    await execution_factory(
        script_id=script.id,
        status=ExecutionStatus.FAILED.value,
        started_at=datetime.now(UTC),
    )

    r = await test_client.get("/")
    assert r.status_code == 200
    # Sidebar + attention section + stat cards all follow the setting.
    assert "Требует внимания" in r.text
    assert "Пропущено сегодня" in r.text
    assert "Планировщик Python-скриптов" in r.text
    assert ">Дашборд<" in r.text


async def test_login_page_renders_in_russian(test_client):
    await test_client.post("/api/locale", json={"locale": "ru"})

    r = await test_client.get("/login")
    assert r.status_code == 200
    assert "Войти" in r.text
    assert "Имя пользователя" in r.text
    assert 'lang="ru"' in r.text


async def test_dashboard_defaults_to_english(test_client):
    r = await test_client.get("/")
    assert r.status_code == 200
    assert "Requires Attention" in r.text or "No scripts yet" in r.text
    assert 'lang="en"' in r.text


async def test_translated_page_still_marks_active_nav(test_client):
    await test_client.post("/api/locale", json={"locale": "ru"})

    r = await test_client.get("/scripts")
    assert r.status_code == 200
    # The nav renders translated labels…
    assert ">Скрипты<" in r.text
    # …while the active-state comparison stays on the raw English page_title,
    # so the current page is still highlighted.
    assert "active" in r.text


async def test_interpolated_counts_translate(test_client, script_factory):
    await test_client.post("/api/locale", json={"locale": "ru"})
    await script_factory(name="ru_count_script", content="print(1)")

    r = await test_client.get("/scripts")
    assert "всего: 1" in r.text
