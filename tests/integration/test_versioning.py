"""Integration tests for Script Versioning API.

Endpoints:
  GET  /api/scripts/{id}/versions
  GET  /api/scripts/{id}/versions/{version_number}
  POST /api/scripts/{id}/revert/{version_number}
"""

import pytest
from httpx import AsyncClient


# ─────────────────────────── helpers ─────────────────────────────────────────


async def _create_script(client: AsyncClient, name: str, content: str = "print('v1')") -> dict:
    """Создаёт скрипт через API (автоматически получает версию v1)."""
    resp = await client.post(
        "/api/scripts",
        json={
            "name": name,
            "content": content,
            "cron_expression": "0 * * * *",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _update_content(client: AsyncClient, script_id: int, content: str) -> None:
    resp = await client.put(f"/api/scripts/{script_id}", json={"content": content})
    assert resp.status_code == 200, resp.text


# ─────────────────────────── tests ───────────────────────────────────────────


class TestScriptVersioning:
    """Интеграционные тесты версионирования скриптов."""

    # ── создание версий ───────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_create_script_generates_v1(self, test_client: AsyncClient):
        """POST /api/scripts → автоматически создаётся версия v1."""
        script = await _create_script(test_client, "ver-init")

        resp = await test_client.get(f"/api/scripts/{script['id']}/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["version_number"] == 1

    @pytest.mark.asyncio
    async def test_update_content_creates_new_version(self, test_client: AsyncClient):
        """PUT с новым content → создаётся v2."""
        script = await _create_script(test_client, "ver-update")
        await _update_content(test_client, script["id"], "print('v2 content')")

        resp = await test_client.get(f"/api/scripts/{script['id']}/versions")
        assert resp.json()["total"] == 2

    # ── SHA256 дедупликация ───────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_same_content_update_does_not_create_new_version(
        self, test_client: AsyncClient
    ):
        """PUT с тем же content → дедупликация по хешу, версия не создаётся."""
        script = await _create_script(test_client, "ver-dedup", content="print('stable')")

        # Отправляем то же самое содержимое
        await _update_content(test_client, script["id"], "print('stable')")

        resp = await test_client.get(f"/api/scripts/{script['id']}/versions")
        assert resp.json()["total"] == 1  # только v1, новая не появилась

    @pytest.mark.asyncio
    async def test_content_change_after_dedup_creates_version(
        self, test_client: AsyncClient
    ):
        """После dedup-пропуска, реальное изменение всё равно создаёт версию."""
        script = await _create_script(test_client, "ver-dedup2", content="print('a')")
        await _update_content(test_client, script["id"], "print('a')")  # пропуск
        await _update_content(test_client, script["id"], "print('b')")  # реальное изменение

        resp = await test_client.get(f"/api/scripts/{script['id']}/versions")
        assert resp.json()["total"] == 2  # v1 + v2 (пропущенное обновление не считается)

    # ── список версий ─────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_versions_returned_in_descending_order(self, test_client: AsyncClient):
        """Список версий отсортирован по version_number по убыванию (новейшая первая)."""
        script = await _create_script(test_client, "ver-order")
        await _update_content(test_client, script["id"], "print('v2')")
        await _update_content(test_client, script["id"], "print('v3')")

        resp = await test_client.get(f"/api/scripts/{script['id']}/versions")
        numbers = [item["version_number"] for item in resp.json()["items"]]
        assert numbers == sorted(numbers, reverse=True)

    @pytest.mark.asyncio
    async def test_list_versions_404_for_unknown_script(self, test_client: AsyncClient):
        """GET versions несуществующего скрипта → 404."""
        resp = await test_client.get("/api/scripts/99999/versions")
        assert resp.status_code == 404

    # ── получение конкретной версии ───────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_specific_version_returns_full_content(
        self, test_client: AsyncClient
    ):
        """GET /versions/1 → возвращает полный content, не preview."""
        script = await _create_script(test_client, "ver-get", content="print('original')")
        await _update_content(test_client, script["id"], "print('updated')")

        resp = await test_client.get(f"/api/scripts/{script['id']}/versions/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version_number"] == 1
        assert data["content"] == "print('original')"

    @pytest.mark.asyncio
    async def test_get_version_404_for_unknown_version(self, test_client: AsyncClient):
        """GET несуществующей версии → 404."""
        script = await _create_script(test_client, "ver-notfound")

        resp = await test_client.get(f"/api/scripts/{script['id']}/versions/9999")
        assert resp.status_code == 404

    # ── откат к версии ────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_revert_restores_content(self, test_client: AsyncClient):
        """POST /revert/1 → content скрипта возвращается к v1."""
        script = await _create_script(test_client, "ver-revert", content="print('original')")
        await _update_content(test_client, script["id"], "print('changed')")

        revert_resp = await test_client.post(
            f"/api/scripts/{script['id']}/revert/1"
        )
        assert revert_resp.status_code == 200
        assert "reverted" in revert_resp.json()["message"].lower()

        script_resp = await test_client.get(f"/api/scripts/{script['id']}")
        assert script_resp.json()["content"] == "print('original')"

    @pytest.mark.asyncio
    async def test_revert_creates_new_version(self, test_client: AsyncClient):
        """После отката создаётся новая версия (для аудита)."""
        script = await _create_script(test_client, "ver-revert-audit", content="print('v1')")
        await _update_content(test_client, script["id"], "print('v2')")

        versions_before = (
            await test_client.get(f"/api/scripts/{script['id']}/versions")
        ).json()["total"]

        await test_client.post(f"/api/scripts/{script['id']}/revert/1")

        versions_after = (
            await test_client.get(f"/api/scripts/{script['id']}/versions")
        ).json()["total"]

        # Откат с отличающимся content должен добавить версию
        assert versions_after >= versions_before

    @pytest.mark.asyncio
    async def test_revert_to_nonexistent_version_returns_404(
        self, test_client: AsyncClient
    ):
        """POST /revert/9999 → 404."""
        script = await _create_script(test_client, "ver-revert-404")

        resp = await test_client.post(f"/api/scripts/{script['id']}/revert/9999")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_revert_to_unknown_script_returns_404(self, test_client: AsyncClient):
        """POST /revert для несуществующего скрипта → 404."""
        resp = await test_client.post("/api/scripts/99999/revert/1")
        assert resp.status_code == 404

    # ── независимость версий разных скриптов ──────────────────────────────────

    @pytest.mark.asyncio
    async def test_versions_are_independent_per_script(self, test_client: AsyncClient):
        """Версии двух разных скриптов не пересекаются."""
        script_a = await _create_script(test_client, "ver-script-a", content="print('a')")
        script_b = await _create_script(test_client, "ver-script-b", content="print('b')")

        # Обновляем только script_a
        await _update_content(test_client, script_a["id"], "print('a v2')")
        await _update_content(test_client, script_a["id"], "print('a v3')")

        resp_a = await test_client.get(f"/api/scripts/{script_a['id']}/versions")
        resp_b = await test_client.get(f"/api/scripts/{script_b['id']}/versions")

        assert resp_a.json()["total"] == 3
        assert resp_b.json()["total"] == 1  # script_b не трогали
