"""Discord webhook sender for crawl-health alerts.

Mirrors the behavior contract of ``plugins/dispatch/client.py``:

* Returns ``True`` on a 2xx response, ``False`` on any failure or skip.
* Never raises — an alert failure must not take down a crawl cycle.
* ``DISCORD_WEBHOOK_URL`` unset → short-circuits with a DEBUG log; the
  boot-time 2-state log in ``shared/logger.py`` is the operational signal.
* Retries only transient failures (5xx, 429, timeout, connect). Other 4xx
  (e.g. 404 deleted webhook) is permanent — fail fast.
"""

from __future__ import annotations

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential,
)

from ...shared.config import get_config
from ...shared.logger import get_logger

logger = get_logger("discord")

_TIMEOUT = httpx.Timeout(connect=2.0, read=8.0, write=2.0, pool=2.0)

_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}

# Discord hard limit for the `content` field.
_MAX_CONTENT_LEN = 2000


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return False


async def send_discord(content: str) -> bool:
    """POST ``content`` to the configured Discord webhook."""
    url = get_config().discord_webhook_url
    if not url:
        logger.debug("discord_send_skipped_unconfigured")
        return False

    if len(content) > _MAX_CONTENT_LEN:
        content = content[: _MAX_CONTENT_LEN - 1] + "…"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3) | stop_after_delay(15),
                wait=wait_exponential(multiplier=0.5, max=4),
                retry=retry_if_exception(_is_retryable),
                reraise=True,
            ):
                with attempt:
                    resp = await client.post(url, json={"content": content})
                    resp.raise_for_status()
        logger.info("discord_sent", chars=len(content))
        return True
    except httpx.HTTPStatusError as exc:
        logger.warning("discord_send_failed", err=f"HTTP {exc.response.status_code}")
        return False
    except RetryError as exc:
        inner = exc.last_attempt.exception() if exc.last_attempt else None
        logger.warning(
            "discord_send_failed",
            err=type(inner).__name__ if inner else "unknown",
            err_msg=str(inner)[:200] if inner else None,
        )
        return False
    except Exception as exc:  # noqa: BLE001 — final safety net
        logger.warning("discord_send_failed", err=type(exc).__name__, err_msg=str(exc)[:200])
        return False


class DiscordNotifier:
    """The Notifier port, backed by the webhook above.

    Thin on purpose: it exists so plugins/health can alert without
    importing this plugin — health depends on core.ports.Notifier, and
    wiring decides that Discord is what satisfies it.
    """

    async def notify(self, content: str) -> bool:
        return await send_discord(content)
