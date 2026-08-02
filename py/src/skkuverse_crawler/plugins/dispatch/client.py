"""Cycle-end ping to the skkuverse-server's FCM dispatch endpoint.

Single async function ``notify_cycle_complete`` is called at the end of
``run_summary_batch``. Behavior contract:

* Returns ``True`` on a 2xx response, ``False`` on any failure or skip.
* Never raises — push latency is a soft guarantee; the server's safety-net
  cron drains the dispatch queue within 30 min if a ping is lost.
* If either ``dispatch_url`` or ``internal_dispatch_token`` is missing from
  ``Config``, the call short-circuits with a single DEBUG log. The boot-time
  3-state log in ``shared/logger.py`` is the operational signal for that
  state — we deliberately do not re-log it on every cycle.
* Retries only on transient failures (5xx, timeout, connect error). 4xx
  (e.g. 401 wrong token) is permanent — fail fast. Total time bounded by
  ``stop_after_delay(15)`` so a single ping cannot monopolize the cron worker.

Server idempotency contract (so retry is safe):

* In-process mutex on the server's ``sweepPending`` short-circuits a
  concurrent same-instance ping. (notices.dispatcher.js:21,168-180,224)
* Per-row Mongo atomic claim with a 5-min ``dispatchClaimedAt`` lease handles
  the cross-instance case (nginx round-robin between api-1 and api-2).
* The server route only logs ``cycleId`` — it does not dedup by it. The id
  exists for log correlation (one cycle = one id, retries inherit it).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential,
)

from ...env import get_config
from ...shared.logger import get_logger

logger = get_logger("dispatch_client")

# Per-attempt timeout. Whole-call timeout is enforced by tenacity's
# ``stop_after_delay(15)``. Connect/read/write/pool decomposed so a slow
# initial TCP handshake doesn't eat the read budget.
_TIMEOUT = httpx.Timeout(connect=2.0, read=8.0, write=2.0, pool=2.0)

# 4xx responses are permanent (auth, schema). Treating them as non-retryable
# avoids burning the retry budget on a state the server will keep rejecting.
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return False


async def _post_once(
    client: httpx.AsyncClient,
    url: str,
    token: str,
    body: dict[str, Any],
) -> httpx.Response:
    response = await client.post(
        url,
        json=body,
        headers={
            "X-Internal-Token": token,
            "Content-Type": "application/json",
        },
    )
    response.raise_for_status()
    return response


async def notify_cycle_complete(
    *,
    source: str,
    cycle_id: str,
    crawled_at: datetime,
) -> bool:
    """POST a cycle-end ping to the dispatch endpoint.

    ``crawled_at`` is named for the server contract's body schema; in this
    code path it actually represents the *summary cycle start time*. The
    server treats it as opaque metadata for log correlation.
    """
    cfg = get_config()
    url = cfg.dispatch_url
    token = cfg.internal_dispatch_token
    if not url or not token:
        # Boot log already announced the state; per-cycle skip is debug-only.
        logger.debug(
            "dispatch_ping_skipped_unconfigured",
            source=source,
            cycle_id=cycle_id,
        )
        return False

    body: dict[str, Any] = {
        "source": source,
        "cycleId": cycle_id,
        "crawledAt": crawled_at.isoformat(),
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3) | stop_after_delay(15),
                wait=wait_exponential(multiplier=0.5, max=4),
                retry=retry_if_exception(_is_retryable),
                reraise=True,
            ):
                with attempt:
                    response = await _post_once(client, url, token, body)
        # Reaching here means a 2xx attempt succeeded.
        payload = _extract_summary(response)
        logger.info(
            "dispatch_ping_sent",
            source=source,
            cycle_id=cycle_id,
            processed=payload.get("processed"),
            sent=payload.get("sent"),
            failed=payload.get("failed"),
        )
        return True
    except httpx.HTTPStatusError as exc:
        # Non-retryable status (e.g. 401). Permanent.
        logger.warning(
            "dispatch_ping_failed",
            source=source,
            cycle_id=cycle_id,
            err=f"HTTP {exc.response.status_code}",
        )
        return False
    except RetryError as exc:
        # All retries exhausted. The wrapped exception is the most recent failure.
        inner = exc.last_attempt.exception() if exc.last_attempt else None
        logger.warning(
            "dispatch_ping_failed",
            source=source,
            cycle_id=cycle_id,
            err=type(inner).__name__ if inner else "unknown",
            err_msg=str(inner)[:200] if inner else None,
        )
        return False
    except Exception as exc:  # noqa: BLE001 — final safety net
        logger.warning(
            "dispatch_ping_failed",
            source=source,
            cycle_id=cycle_id,
            err=type(exc).__name__,
            err_msg=str(exc)[:200],
        )
        return False


def _extract_summary(response: httpx.Response) -> dict[str, Any]:
    """Pull ``{processed, sent, failed}`` from the server envelope.

    Server response shape: ``{"meta": {...}, "data": {processed, sent, ...}}``.
    Tolerant of malformed JSON or unexpected shapes — returns ``{}`` on miss.
    """
    try:
        body = response.json()
    except ValueError:
        return {}
    if not isinstance(body, dict):
        return {}
    data = body.get("data")
    return data if isinstance(data, dict) else {}
