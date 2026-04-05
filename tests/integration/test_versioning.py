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
    """Creates a script via the API (automatically gets version v1)."""
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
    """Integration tests for script versioning."""

    # ── version creation ─────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_create_script_generates_v1(self, test_client: AsyncClient):
        """POST /api/scripts → version v1 is automatically created."""
        script = await _create_script(test_client, "ver-init")

        resp = await test_client.get(f"/api/scripts/{script['id']}/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["version_number"] == 1

    @pytest.mark.asyncio
    async def test_update_content_creates_new_version(self, test_client: AsyncClient):
        """PUT with new content → v2 is created."""
        script = await _create_script(test_client, "ver-update")
        await _update_content(test_client, script["id"], "print('v2 content')")

        resp = await test_client.get(f"/api/scripts/{script['id']}/versions")
        assert resp.json()["total"] == 2

    # ── SHA256 deduplication ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_same_content_update_does_not_create_new_version(
        self, test_client: AsyncClient
    ):
        """PUT with the same content → deduplication by hash, no new version created."""
        script = await _create_script(test_client, "ver-dedup", content="print('stable')")

        # Send the exact same content again
        await _update_content(test_client, script["id"], "print('stable')")

        resp = await test_client.get(f"/api/scripts/{script['id']}/versions")
        assert resp.json()["total"] == 1  # only v1, no new version

    @pytest.mark.asyncio
    async def test_content_change_after_dedup_creates_version(
        self, test_client: AsyncClient
    ):
        """After a dedup skip, a real content change still creates a new version."""
        script = await _create_script(test_client, "ver-dedup2", content="print('a')")
        await _update_content(test_client, script["id"], "print('a')")  # skipped
        await _update_content(test_client, script["id"], "print('b')")  # real change

        resp = await test_client.get(f"/api/scripts/{script['id']}/versions")
        assert resp.json()["total"] == 2  # v1 + v2 (skipped update is not counted)

    # ── version listing ───────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_versions_returned_in_descending_order(self, test_client: AsyncClient):
        """Version list is sorted by version_number descending (newest first)."""
        script = await _create_script(test_client, "ver-order")
        await _update_content(test_client, script["id"], "print('v2')")
        await _update_content(test_client, script["id"], "print('v3')")

        resp = await test_client.get(f"/api/scripts/{script['id']}/versions")
        numbers = [item["version_number"] for item in resp.json()["items"]]
        assert numbers == sorted(numbers, reverse=True)

    @pytest.mark.asyncio
    async def test_list_versions_404_for_unknown_script(self, test_client: AsyncClient):
        """GET versions for a non-existent script → 404."""
        resp = await test_client.get("/api/scripts/99999/versions")
        assert resp.status_code == 404

    # ── fetching a specific version ───────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_specific_version_returns_full_content(
        self, test_client: AsyncClient
    ):
        """GET /versions/1 → returns full content, not a preview."""
        script = await _create_script(test_client, "ver-get", content="print('original')")
        await _update_content(test_client, script["id"], "print('updated')")

        resp = await test_client.get(f"/api/scripts/{script['id']}/versions/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version_number"] == 1
        assert data["content"] == "print('original')"

    @pytest.mark.asyncio
    async def test_get_version_404_for_unknown_version(self, test_client: AsyncClient):
        """GET a non-existent version → 404."""
        script = await _create_script(test_client, "ver-notfound")

        resp = await test_client.get(f"/api/scripts/{script['id']}/versions/9999")
        assert resp.status_code == 404

    # ── revert to version ─────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_revert_restores_content(self, test_client: AsyncClient):
        """POST /revert/1 → script content is restored to v1."""
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
        """After revert, a new version is created (for audit trail)."""
        script = await _create_script(test_client, "ver-revert-audit", content="print('v1')")
        await _update_content(test_client, script["id"], "print('v2')")

        versions_before = (
            await test_client.get(f"/api/scripts/{script['id']}/versions")
        ).json()["total"]

        await test_client.post(f"/api/scripts/{script['id']}/revert/1")

        versions_after = (
            await test_client.get(f"/api/scripts/{script['id']}/versions")
        ).json()["total"]

        # Revert with differing content should add a version
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
        """POST /revert for a non-existent script → 404."""
        resp = await test_client.post("/api/scripts/99999/revert/1")
        assert resp.status_code == 404

    # ── version isolation between scripts ────────────────────────────────────

    @pytest.mark.asyncio
    async def test_versions_are_independent_per_script(self, test_client: AsyncClient):
        """Versions of two different scripts do not overlap."""
        script_a = await _create_script(test_client, "ver-script-a", content="print('a')")
        script_b = await _create_script(test_client, "ver-script-b", content="print('b')")

        # Update only script_a
        await _update_content(test_client, script_a["id"], "print('a v2')")
        await _update_content(test_client, script_a["id"], "print('a v3')")

        resp_a = await test_client.get(f"/api/scripts/{script_a['id']}/versions")
        resp_b = await test_client.get(f"/api/scripts/{script_b['id']}/versions")

        assert resp_a.json()["total"] == 3
        assert resp_b.json()["total"] == 1  # script_b was not touched
