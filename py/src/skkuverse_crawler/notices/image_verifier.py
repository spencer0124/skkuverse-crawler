"""
Verify that the absolute image URLs we baked into a notice's content are
actually reachable.

Why this exists:
SKKU's image server (`www.skku.edu/_attach/image/...`) does Referer-based
hot-link blocking. A `curl` without `Referer` returns HTTP 404. The crawler
already runs with a browser-like User-Agent and the page URL as Referer,
so we can detect broken/missing/blocked images at crawl time and log them
for ops visibility — instead of finding out from a user reporting blank
images in the mobile app.

This is best-effort: failures are logged, never raised. The notice still
gets ingested.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx
from bs4 import BeautifulSoup

from ..shared.logger import get_logger

logger = get_logger("image_verifier")

_TIMEOUT = httpx.Timeout(5.0, connect=3.0)
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


@dataclass
class ImageCheckResult:
    checked: int = 0
    broken: list[str] = field(default_factory=list)


def _extract_absolute_image_urls(html: str | None) -> list[str]:
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return []

    urls: list[str] = []
    for img in soup.select("img[src]"):
        src = img.get("src")
        if not isinstance(src, str) or not src:
            continue
        if src.startswith(("data:", "mailto:", "tel:")):
            continue
        # Only verify absolute http(s) URLs — anything still relative
        # didn't get normalized upstream and we have no base here.
        if not src.startswith(("http://", "https://")):
            continue
        urls.append(src)
    return urls


async def _head_check(client: httpx.AsyncClient, url: str, referer: str) -> bool:
    """Returns True if the image is reachable, False otherwise."""
    try:
        resp = await client.head(
            url,
            headers={"Referer": referer},
            follow_redirects=True,
        )
        return 200 <= resp.status_code < 400
    except httpx.HTTPError:
        return False
    except Exception:
        return False


async def verify_notice_images(
    content_html: str | None,
    source_url: str,
) -> ImageCheckResult:
    """
    HEAD-fetch every absolute `<img src>` in `content_html` using
    `source_url` as the Referer. Returns a summary that callers can log.

    Best-effort: any unexpected failure is swallowed.
    """
    urls = _extract_absolute_image_urls(content_html)
    if not urls:
        return ImageCheckResult()

    result = ImageCheckResult(checked=len(urls))
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers={"User-Agent": _BROWSER_UA},
        ) as client:
            checks = await asyncio.gather(
                *[_head_check(client, url, source_url) for url in urls],
                return_exceptions=False,
            )
        for url, ok in zip(urls, checks):
            if not ok:
                result.broken.append(url)
    except Exception as exc:
        logger.warning("image_verify_pipeline_failed", error=str(exc))

    return result
