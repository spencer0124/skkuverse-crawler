"""HTTP for the bus upstreams. Fetch and decode only — no normalising.

Kept apart from `hssc.py` / `jongro.py` so those stay pure and replayable
against captured fixtures. Everything here is the part that cannot be
tested by replay, and it is deliberately thin for that reason.

Credentials arrive as arguments, never read from the environment: this
module lives under `modules/`, which may not touch `os.environ`, import
`plugins/`, or reach for `shared.db`. The HSSC endpoint has no separate
key — the whole URL is the credential — so it is passed the same way and
never logged.
"""

from __future__ import annotations

from typing import Any, Mapping

import httpx

# The upstreams are slow enough that a tight timeout produces false
# failures, and a 10s poller cannot afford to wait much longer than one
# tick. Matches the TypeScript's axios timeout.
TIMEOUT_SECONDS = 10.0


class UpstreamError(RuntimeError):
    """The upstream could not be reached or did not return JSON.

    Distinct from a response that says "no data": this means the tick has
    nothing to say and the stored document must be left alone. Callers
    must not turn it into an empty payload.
    """


async def fetch_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
) -> Any:
    """GET and decode. Raises `UpstreamError` for anything else.

    The URL is never included in the error: for HSSC it IS the credential,
    and this message ends up in logs. `headers` gets the same treatment for
    the same reason — Naver's two keys travel there.
    """
    try:
        # follow_redirects, because axios does (maxRedirects: 5) and these
        # upstreams are plain http://. If ws.bus.go.kr ever adds an
        # http->https redirect, the default would take the crawler
        # permanently dark while reporting "upstream unavailable" — a
        # message pointing at the network rather than at this line.
        response = await client.get(
            url,
            timeout=TIMEOUT_SECONDS,
            follow_redirects=True,
            headers=dict(headers) if headers else None,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise UpstreamError(f"HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise UpstreamError(type(exc).__name__) from exc
    except ValueError as exc:  # json decode
        raise UpstreamError("response was not JSON") from exc
