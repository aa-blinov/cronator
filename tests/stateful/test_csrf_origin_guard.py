"""P0: CSRF via Basic Auth. Browsers auto-attach cached Basic Auth
credentials to same-origin requests regardless of which page initiated
them, so a form on an attacker's site can submit a state-changing
request to Cronator and have the browser silently authenticate it.

Mitigation: on state-changing methods, if the browser sent an `Origin`
header (it always does for cross-origin requests, and modern browsers
send it for same-origin ones too), it must match this app's own origin.
Requests with no Origin header at all (curl, server-to-server API
clients using Basic Auth directly) are left alone — this guard targets
the browser-credential-replay vector, not API automation.
"""

import pytest

pytestmark = pytest.mark.asyncio


class TestCsrfOriginGuard:
    async def test_mismatched_origin_blocked_on_post(self, test_client):
        r = await test_client.post(
            "/api/scripts",
            json={"name": "csrf-test", "content": "print(1)"},
            headers={"Origin": "http://evil.example.com"},
        )
        assert r.status_code == 403

    async def test_matching_origin_allowed(self, test_client):
        r = await test_client.post(
            "/api/scripts",
            json={"name": "csrf-origin-ok", "cron_expression": "0 0 * * *", "script_content": "print(1)"},
            headers={"Origin": "http://test"},
        )
        assert r.status_code in (200, 201), r.text

    async def test_no_origin_header_allowed(self, test_client):
        """Non-browser clients (curl, CI) don't send Origin at all."""
        r = await test_client.post(
            "/api/scripts",
            json={"name": "csrf-no-origin-ok", "cron_expression": "0 0 * * *", "script_content": "print(1)"},
        )
        assert r.status_code in (200, 201), r.text

    async def test_https_origin_allowed_behind_tls_terminating_proxy(self, test_client):
        """Reverse proxy terminates TLS and forwards X-Forwarded-Proto:
        https, so request.url.scheme is 'http' even though the browser's
        real origin (what it sends in the Origin header) is https."""
        r = await test_client.post(
            "/api/scripts",
            json={"name": "csrf-https-proxy-ok", "cron_expression": "0 0 * * *", "script_content": "print(1)"},
            headers={"Origin": "https://test", "X-Forwarded-Proto": "https"},
        )
        assert r.status_code in (200, 201), r.text

    async def test_mismatched_origin_does_not_block_get(self, test_client):
        """Only state-changing methods are guarded."""
        r = await test_client.get("/api/scripts", headers={"Origin": "http://evil.example.com"})
        assert r.status_code == 200
