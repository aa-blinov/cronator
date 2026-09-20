"""Perf: pages and static assets were served uncompressed with no cache
headers — a ~170KB HTML page plus ~170KB CodeMirror JS plus ~105KB CSS,
every single navigation, with nothing telling the browser to keep them
around. Real-world symptom: a remote user reported /scripts/new "very
slow to render" — server-side it was ~190ms, the weight was all in
transfer + no caching across page loads.
"""

import pytest

pytestmark = pytest.mark.asyncio


class TestGzipCompression:
    async def test_large_html_response_is_gzipped(self, test_client):
        r = await test_client.get(
            "/scripts/new", headers={"Accept-Encoding": "gzip"}
        )
        assert r.status_code == 200
        assert r.headers.get("content-encoding") == "gzip"


class TestStaticAssetCaching:
    async def test_static_assets_revalidate_via_etag(self, test_client):
        """no-cache (not no-store): the browser still avoids re-transferring
        the body via a conditional GET against the ETag StaticFiles already
        sets — it just never risks serving a stale asset after a deploy,
        unlike a fixed max-age would."""
        r = await test_client.get("/static/app.js")
        assert r.status_code == 200
        assert r.headers.get("cache-control") == "no-cache"
        etag = r.headers.get("etag")
        assert etag

        r2 = await test_client.get("/static/app.js", headers={"If-None-Match": etag})
        assert r2.status_code == 304
