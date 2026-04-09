from __future__ import annotations

import asyncio

import httpx

from ..shared.logger import get_logger

logger = get_logger("ai_client")

_MAX_RETRIES = 3


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


class AiClient:
    """HTTP client for the skkuverse-ai summarization service.

    Separate from shared/fetcher.py: fetcher is for HTML GET with browser UA
    and 500ms rate limit. This client does JSON POST with 30s timeout.
    """

    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
        )

    async def summarize(
        self, title: str, category: str, clean_text: str,
        date: str | None = None,
    ) -> dict:
        last_error: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                payload: dict[str, str] = {
                    "title": title,
                    "category": category,
                    "cleanText": clean_text,
                }
                if date:
                    payload["date"] = date
                resp = await self._client.post(
                    "/api/notices/summarize",
                    json=payload,
                )
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                last_error = exc
                if not _is_retryable(exc):
                    raise
                if attempt < _MAX_RETRIES:
                    backoff = 2 ** (attempt - 1)
                    logger.warning(
                        "retrying_summarize",
                        attempt=attempt,
                        backoff=backoff,
                        error=str(exc),
                    )
                    await asyncio.sleep(backoff)

        logger.error("summarize_retries_exhausted")
        raise last_error  # type: ignore[misc]

    async def close(self) -> None:
        await self._client.aclose()
