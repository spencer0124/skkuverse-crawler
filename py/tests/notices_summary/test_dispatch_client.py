"""Tests for the cycle-end FCM dispatch ping client.

Server idempotency contract is unit-tested on the server side; here we
verify the client's behavior against a mocked HTTP endpoint:

* 2xx → returns True, log captures processed/sent.
* 4xx → returns False without retry (auth/schema is permanent).
* 5xx → retries up to 3 times, then returns False.
* Network errors (Connect/Timeout) → same retry behavior as 5xx.
* Either env var unset → no HTTP call, returns False.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from skkuverse_crawler.notices_summary.dispatch_client import notify_cycle_complete
from skkuverse_crawler.shared.config import reset_config

URL = "http://test-api/internal/notices/dispatch-pending"
TOKEN = "test-token-64"  # noqa: S105 — fixture, not real
SUCCESS_BODY = {
    "meta": {"lang": "ko"},
    "data": {
        "status": "ok",
        "source": "summary",
        "processed": 3,
        "sent": 2,
        "failed": 1,
        "skippedNoTopics": 0,
        "durationMs": 12,
    },
}


@pytest.fixture
def enabled_config(monkeypatch):
    monkeypatch.setenv("DISPATCH_URL", URL)
    monkeypatch.setenv("INTERNAL_DISPATCH_TOKEN", TOKEN)
    reset_config()
    yield
    reset_config()


def _kwargs():
    return {
        "source": "summary",
        "cycle_id": "abc12345",
        "crawled_at": datetime(2026, 5, 4, 6, 20, 0, tzinfo=UTC),
    }


class TestSuccessPath:
    @respx.mock
    async def test_returns_true_on_2xx(self, enabled_config):
        route = respx.post(URL).respond(json=SUCCESS_BODY, status_code=200)
        ok = await notify_cycle_complete(**_kwargs())
        assert ok is True
        assert route.called
        # request body shape
        body = route.calls[0].request.read()
        assert b'"source"' in body and b'"summary"' in body
        assert b'"cycleId"' in body and b'"abc12345"' in body
        assert b'"crawledAt"' in body
        # auth header
        assert route.calls[0].request.headers.get("X-Internal-Token") == TOKEN

    @respx.mock
    async def test_tolerates_unexpected_response_shape(self, enabled_config):
        # Server contract may evolve; we should still accept any 2xx.
        respx.post(URL).respond(json={"unexpected": "shape"}, status_code=200)
        ok = await notify_cycle_complete(**_kwargs())
        assert ok is True

    @respx.mock
    async def test_tolerates_non_json_body(self, enabled_config):
        respx.post(URL).respond(content=b"OK", status_code=200)
        ok = await notify_cycle_complete(**_kwargs())
        assert ok is True


class TestPermanentFailure:
    @respx.mock
    async def test_401_returns_false_no_retry(self, enabled_config):
        route = respx.post(URL).respond(
            json={"error": {"code": "UNAUTHORIZED"}}, status_code=401
        )
        ok = await notify_cycle_complete(**_kwargs())
        assert ok is False
        # 4xx is non-retryable: exactly 1 call
        assert route.call_count == 1

    @respx.mock
    async def test_400_returns_false_no_retry(self, enabled_config):
        route = respx.post(URL).respond(status_code=400)
        ok = await notify_cycle_complete(**_kwargs())
        assert ok is False
        assert route.call_count == 1


class TestTransientFailureRetries:
    @respx.mock
    async def test_502_retries_then_gives_up(self, enabled_config):
        route = respx.post(URL).respond(status_code=502)
        ok = await notify_cycle_complete(**_kwargs())
        assert ok is False
        # 3 attempts (the tenacity stop_after_attempt cap)
        assert route.call_count == 3

    @respx.mock
    async def test_503_then_200_recovers(self, enabled_config):
        route = respx.post(URL).mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(200, json=SUCCESS_BODY),
            ]
        )
        ok = await notify_cycle_complete(**_kwargs())
        assert ok is True
        assert route.call_count == 2

    @respx.mock
    async def test_connect_error_retries_then_gives_up(self, enabled_config):
        route = respx.post(URL).mock(side_effect=httpx.ConnectError("nope"))
        ok = await notify_cycle_complete(**_kwargs())
        assert ok is False
        assert route.call_count == 3

    @respx.mock
    async def test_timeout_retries_then_gives_up(self, enabled_config):
        route = respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
        ok = await notify_cycle_complete(**_kwargs())
        assert ok is False
        assert route.call_count == 3


class TestUnconfigured:
    @respx.mock
    async def test_both_unset_returns_false_without_http(self, monkeypatch):
        monkeypatch.delenv("DISPATCH_URL", raising=False)
        monkeypatch.delenv("INTERNAL_DISPATCH_TOKEN", raising=False)
        reset_config()
        route = respx.post(URL)  # no responder; would fail if hit
        ok = await notify_cycle_complete(**_kwargs())
        assert ok is False
        assert route.call_count == 0
        reset_config()

    @respx.mock
    async def test_only_url_set_returns_false_without_http(self, monkeypatch):
        monkeypatch.setenv("DISPATCH_URL", URL)
        monkeypatch.delenv("INTERNAL_DISPATCH_TOKEN", raising=False)
        reset_config()
        route = respx.post(URL)
        ok = await notify_cycle_complete(**_kwargs())
        assert ok is False
        assert route.call_count == 0
        reset_config()

    @respx.mock
    async def test_only_token_set_returns_false_without_http(self, monkeypatch):
        monkeypatch.delenv("DISPATCH_URL", raising=False)
        monkeypatch.setenv("INTERNAL_DISPATCH_TOKEN", TOKEN)
        reset_config()
        route = respx.post(URL)
        ok = await notify_cycle_complete(**_kwargs())
        assert ok is False
        assert route.call_count == 0
        reset_config()


class TestNeverRaises:
    @respx.mock
    async def test_unexpected_exception_swallowed(self, enabled_config):
        # Simulate an exception type the retry filter doesn't cover (e.g. RuntimeError
        # raised inside the request pipeline). The final safety net must catch it.
        respx.post(URL).mock(side_effect=RuntimeError("unexpected"))
        ok = await notify_cycle_complete(**_kwargs())
        assert ok is False
