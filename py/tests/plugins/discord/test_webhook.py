from __future__ import annotations

import httpx
import pytest
import respx

from skkuverse_crawler.shared.config import init_config, reset_config
from skkuverse_crawler.plugins.discord.webhook import send_discord

WEBHOOK = "https://discord.com/api/webhooks/123/token-abc"


@pytest.fixture()
def _webhook_env(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", WEBHOOK)
    init_config(force=True)
    yield
    reset_config()


class TestSendDiscord:
    async def test_unconfigured_skips(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        init_config(force=True)
        assert await send_discord("hello") is False

    @respx.mock
    async def test_success(self, _webhook_env):
        route = respx.post(WEBHOOK).respond(204)
        assert await send_discord("🚨 test") is True
        assert route.called
        import json
        body = json.loads(route.calls[0].request.content)
        assert body == {"content": "🚨 test"}

    @respx.mock
    async def test_retries_transient_then_succeeds(self, _webhook_env):
        route = respx.post(WEBHOOK)
        route.side_effect = [httpx.Response(503), httpx.Response(204)]
        assert await send_discord("retry me") is True
        assert route.call_count == 2

    @respx.mock
    async def test_permanent_4xx_fails_fast(self, _webhook_env):
        route = respx.post(WEBHOOK).respond(404)
        assert await send_discord("gone") is False
        assert route.call_count == 1

    @respx.mock
    async def test_never_raises_on_connect_error(self, _webhook_env):
        respx.post(WEBHOOK).mock(side_effect=httpx.ConnectError("boom"))
        assert await send_discord("x") is False

    @respx.mock
    async def test_truncates_over_2000_chars(self, _webhook_env):
        route = respx.post(WEBHOOK).respond(204)
        await send_discord("a" * 3000)
        import json
        body = json.loads(route.calls[0].request.content)
        assert len(body["content"]) == 2000
        assert body["content"].endswith("…")
