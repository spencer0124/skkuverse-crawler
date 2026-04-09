from __future__ import annotations

import asyncio
import time

import httpx

from .logger import get_logger

logger = get_logger("fetcher")

DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_DELAY_MS = 500


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


class Fetcher:
    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        delay_ms: int = DEFAULT_DELAY_MS,
    ) -> None:
        self.max_retries = max_retries
        self.delay_ms = delay_ms
        self._last_request_time: float = 0.0
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SKKUverseCrawler/1.0)"},
            follow_redirects=True,
        )

    async def _rate_limit(self) -> None:
        now = time.monotonic()
        elapsed_ms = (now - self._last_request_time) * 1000
        if elapsed_ms < self.delay_ms:
            await asyncio.sleep((self.delay_ms - elapsed_ms) / 1000)

    async def _fetch_with_retry(self, url: str) -> httpx.Response:
        await self._rate_limit()

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                self._last_request_time = time.monotonic()
                resp = await self._client.get(url)
                resp.raise_for_status()
                return resp
            except Exception as exc:
                last_error = exc
                if not _is_retryable(exc):
                    logger.warning("non_retryable_error", url=url, error=str(exc))
                    raise
                if attempt < self.max_retries:
                    backoff = (2 ** (attempt - 1)) * 1.0
                    logger.warning(
                        "retrying_fetch", url=url, attempt=attempt, backoff=backoff
                    )
                    await asyncio.sleep(backoff)

        logger.error("all_retries_exhausted", url=url)
        raise last_error  # type: ignore[misc]

    async def fetch(self, url: str) -> str:
        return (await self._fetch_with_retry(url)).text

    async def fetch_binary(self, url: str) -> bytes:
        return (await self._fetch_with_retry(url)).content

    async def close(self) -> None:
        await self._client.aclose()
