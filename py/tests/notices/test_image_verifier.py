"""
Tests for image_verifier — fetches every <img src> in a notice with
the page Referer, reports broken/missing images, and detects dimensions.
"""
from __future__ import annotations

import struct
import zlib

import httpx
import respx

from skkuverse_crawler.notices.image_verifier import (
    _parse_dimensions,
    verify_notice_images,
)


SOURCE_URL = "https://www.skku.edu/skku/campus/skk_comm/notice01.do?mode=view&articleNo=1"


def _make_png(w: int, h: int) -> bytes:
    """Generate a minimal valid PNG with the given dimensions."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    ihdr_crc = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF)
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + ihdr_crc
    raw = b"\x00" * (w * 3 + 1) * h
    compressed = zlib.compress(raw)
    idat_crc = struct.pack(">I", zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF)
    idat = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + idat_crc
    iend_crc = struct.pack(">I", zlib.crc32(b"IEND") & 0xFFFFFFFF)
    iend = struct.pack(">I", 0) + b"IEND" + iend_crc
    return sig + ihdr + idat + iend


# ── Unit: _parse_dimensions ───────────────────────────


def test_parse_dimensions_valid_png():
    png = _make_png(800, 600)
    assert _parse_dimensions(png) == (800, 600)


def test_parse_dimensions_invalid_bytes():
    assert _parse_dimensions(b"not an image") is None


def test_parse_dimensions_empty():
    assert _parse_dimensions(b"") is None


# ── Integration: verify_notice_images ─────────────────


class TestVerifyNoticeImages:
    @respx.mock
    async def test_returns_empty_when_no_images(self):
        result = await verify_notice_images("<p>just text</p>", SOURCE_URL)
        assert result.checked == 0
        assert result.broken == []
        assert result.dimensions == {}

    @respx.mock
    async def test_returns_empty_when_html_is_none(self):
        result = await verify_notice_images(None, SOURCE_URL)
        assert result.checked == 0
        assert result.broken == []

    @respx.mock
    async def test_all_images_ok_with_dimensions(self):
        png = _make_png(100, 50)
        respx.get("https://www.skku.edu/_attach/image/a.jpg").respond(
            206, content=png,
        )
        respx.get("https://www.skku.edu/_attach/image/b.jpg").respond(
            206, content=_make_png(200, 100),
        )

        html = (
            '<img src="https://www.skku.edu/_attach/image/a.jpg">'
            '<img src="https://www.skku.edu/_attach/image/b.jpg">'
        )
        result = await verify_notice_images(html, SOURCE_URL)
        assert result.checked == 2
        assert result.broken == []
        assert result.dimensions["https://www.skku.edu/_attach/image/a.jpg"] == (100, 50)
        assert result.dimensions["https://www.skku.edu/_attach/image/b.jpg"] == (200, 100)

    @respx.mock
    async def test_broken_image_404_is_reported(self):
        respx.get("https://www.skku.edu/_attach/image/missing.jpg").respond(404)
        html = '<img src="https://www.skku.edu/_attach/image/missing.jpg">'
        result = await verify_notice_images(html, SOURCE_URL)
        assert result.checked == 1
        assert result.broken == ["https://www.skku.edu/_attach/image/missing.jpg"]
        assert result.dimensions == {}

    @respx.mock
    async def test_sends_referer_header_from_source_url(self):
        route = respx.get("https://www.skku.edu/_attach/image/a.jpg").respond(
            200, content=_make_png(10, 10),
        )
        html = '<img src="https://www.skku.edu/_attach/image/a.jpg">'
        await verify_notice_images(html, SOURCE_URL)
        assert route.called
        request = route.calls[0].request
        assert request.headers["Referer"] == SOURCE_URL

    @respx.mock
    async def test_sends_range_header(self):
        route = respx.get("https://www.skku.edu/_attach/image/a.jpg").respond(
            206, content=_make_png(10, 10),
        )
        html = '<img src="https://www.skku.edu/_attach/image/a.jpg">'
        await verify_notice_images(html, SOURCE_URL)
        request = route.calls[0].request
        assert "Range" in request.headers

    @respx.mock
    async def test_skips_data_uris(self):
        html = '<img src="data:image/png;base64,iVBORw0KGgo=">'
        result = await verify_notice_images(html, SOURCE_URL)
        assert result.checked == 0
        assert result.broken == []

    @respx.mock
    async def test_skips_relative_urls(self):
        html = '<img src="/_attach/foo.jpg">'
        result = await verify_notice_images(html, SOURCE_URL)
        assert result.checked == 0
        assert result.broken == []

    @respx.mock
    async def test_network_error_treated_as_broken(self):
        respx.get("https://www.skku.edu/_attach/image/x.jpg").mock(
            side_effect=httpx.ConnectError("boom")
        )
        html = '<img src="https://www.skku.edu/_attach/image/x.jpg">'
        result = await verify_notice_images(html, SOURCE_URL)
        assert result.checked == 1
        assert result.broken == ["https://www.skku.edu/_attach/image/x.jpg"]

    @respx.mock
    async def test_full_response_200_still_detects_dimensions(self):
        """Server doesn't support Range — returns full 200 with body."""
        png = _make_png(640, 480)
        respx.get("https://www.skku.edu/img.png").respond(
            200,
            content=png,
            headers={"Content-Length": str(len(png))},
        )
        html = '<img src="https://www.skku.edu/img.png">'
        result = await verify_notice_images(html, SOURCE_URL)
        assert result.checked == 1
        assert result.broken == []
        assert result.dimensions["https://www.skku.edu/img.png"] == (640, 480)

    @respx.mock
    async def test_oversized_image_skips_dimensions(self):
        """Content-Length > 5MB → reachable but no dimension detection."""
        respx.get("https://www.skku.edu/huge.png").respond(
            200,
            content=b"small body",  # body is small but header says huge
            headers={"Content-Length": str(10 * 1024 * 1024)},
        )
        html = '<img src="https://www.skku.edu/huge.png">'
        result = await verify_notice_images(html, SOURCE_URL)
        assert result.checked == 1
        assert result.broken == []
        assert result.dimensions == {}

    @respx.mock
    async def test_mixed_results(self):
        respx.get("https://www.skku.edu/a.jpg").respond(
            206, content=_make_png(300, 200),
        )
        respx.get("https://www.skku.edu/b.jpg").respond(404)
        respx.get("https://www.skku.edu/c.jpg").respond(
            200, content=_make_png(50, 50),
        )
        html = (
            '<img src="https://www.skku.edu/a.jpg">'
            '<img src="https://www.skku.edu/b.jpg">'
            '<img src="https://www.skku.edu/c.jpg">'
        )
        result = await verify_notice_images(html, SOURCE_URL)
        assert result.checked == 3
        assert result.broken == ["https://www.skku.edu/b.jpg"]
        assert result.dimensions["https://www.skku.edu/a.jpg"] == (300, 200)
        assert "https://www.skku.edu/b.jpg" not in result.dimensions
        assert result.dimensions["https://www.skku.edu/c.jpg"] == (50, 50)
