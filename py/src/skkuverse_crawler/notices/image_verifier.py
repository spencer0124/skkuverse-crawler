"""
Verify that the absolute image URLs we baked into a notice's content are
actually reachable, and detect their dimensions.

Why this exists:
SKKU's image server (`www.skku.edu/_attach/image/...`) does Referer-based
hot-link blocking. A `curl` without `Referer` returns HTTP 404. The crawler
already runs with a browser-like User-Agent and the page URL as Referer,
so we can detect broken/missing/blocked images at crawl time and log them
for ops visibility — instead of finding out from a user reporting blank
images in the mobile app.

Dimension detection piggybacks on the reachability check: a partial GET
(first 32 KB via Range header) is attempted first; if the server doesn't
support Range, a full GET is used — but only when Content-Length is below
``_MAX_FULL_GET_BYTES`` (5 MB default) to avoid downloading huge files
just for dimensions.

This is best-effort: failures are logged, never raised. The notice still
gets ingested.
"""
from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass, field

import httpx
import imagesize
from bs4 import BeautifulSoup

from ..shared.logger import get_logger

logger = get_logger("image_verifier")

_TIMEOUT = httpx.Timeout(5.0, connect=3.0)
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_RANGE_BYTES = 32_768  # 32 KB — enough for image headers
_MAX_FULL_GET_BYTES = 5 * 1024 * 1024  # 5 MB — skip dimension detection above this


@dataclass
class ImageCheckResult:
    checked: int = 0
    broken: list[str] = field(default_factory=list)
    dimensions: dict[str, tuple[int, int]] = field(default_factory=dict)


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


def _parse_dimensions(data: bytes) -> tuple[int, int] | None:
    """Extract (width, height) from image bytes. Returns None on failure."""
    try:
        w, h = imagesize.get(io.BytesIO(data))
        if w > 0 and h > 0:
            return (w, h)
    except Exception:
        pass
    return None


async def _check_and_measure(
    client: httpx.AsyncClient,
    url: str,
    referer: str,
) -> tuple[bool, tuple[int, int] | None]:
    """Check reachability and detect dimensions for a single image.

    Returns ``(reachable, dimensions)`` where dimensions is ``(w, h)``
    or ``None`` if detection failed or was skipped.

    Strategy:
    1. Try partial GET with Range header (first 32 KB).
    2. If server returns 200 (Range not supported), check Content-Length;
       if ≤ 5 MB, use the response body; otherwise skip dimensions.
    3. If server returns 206 (partial), parse dimensions from the chunk.
    """
    try:
        resp = await client.get(
            url,
            headers={"Referer": referer, "Range": f"bytes=0-{_RANGE_BYTES - 1}"},
            follow_redirects=True,
        )
        if resp.status_code >= 400:
            return (False, None)

        reachable = True
        data = resp.content

        if resp.status_code == 206:
            # Partial content — parse dimensions from the chunk
            dims = _parse_dimensions(data)
            return (reachable, dims)

        # Full response (200) — server doesn't support Range
        content_length = resp.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
                if size > _MAX_FULL_GET_BYTES:
                    logger.debug(
                        "image_too_large_for_dimensions",
                        url=url,
                        size=size,
                    )
                    return (reachable, None)
            except ValueError:
                pass

        # Response body is available (server sent full content or small enough)
        if len(data) <= _MAX_FULL_GET_BYTES:
            dims = _parse_dimensions(data)
            return (reachable, dims)

        return (reachable, None)

    except httpx.HTTPError:
        return (False, None)
    except Exception:
        return (False, None)


async def verify_notice_images(
    content_html: str | None,
    source_url: str,
) -> ImageCheckResult:
    """
    Fetch every absolute ``<img src>`` in ``content_html`` using
    ``source_url`` as the Referer.  Returns reachability + dimensions.

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
                *[_check_and_measure(client, url, source_url) for url in urls],
                return_exceptions=False,
            )
        for url, (ok, dims) in zip(urls, checks):
            if not ok:
                result.broken.append(url)
            if dims is not None:
                result.dimensions[url] = dims
    except Exception as exc:
        logger.warning("image_verify_pipeline_failed", error=str(exc))

    return result
