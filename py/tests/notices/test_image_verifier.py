"""
Tests for image_verifier — HEAD-fetches every <img src> in a notice with
the page Referer and reports broken/missing images.
"""
from __future__ import annotations

import httpx
import respx

from skkuverse_crawler.notices.image_verifier import (
    verify_notice_images,
)


SOURCE_URL = "https://www.skku.edu/skku/campus/skk_comm/notice01.do?mode=view&articleNo=1"


class TestVerifyNoticeImages:
    @respx.mock
    async def test_returns_empty_when_no_images(self):
        result = await verify_notice_images("<p>just text</p>", SOURCE_URL)
        assert result.checked == 0
        assert result.broken == []

    @respx.mock
    async def test_returns_empty_when_html_is_none(self):
        result = await verify_notice_images(None, SOURCE_URL)
        assert result.checked == 0
        assert result.broken == []

    @respx.mock
    async def test_all_images_ok(self):
        # Mock both URLs returning 200
        respx.head("https://www.skku.edu/_attach/image/a.jpg").respond(200)
        respx.head("https://www.skku.edu/_attach/image/b.jpg").respond(200)

        html = (
            '<img src="https://www.skku.edu/_attach/image/a.jpg">'
            '<img src="https://www.skku.edu/_attach/image/b.jpg">'
        )
        result = await verify_notice_images(html, SOURCE_URL)
        assert result.checked == 2
        assert result.broken == []

    @respx.mock
    async def test_broken_image_404_is_reported(self):
        respx.head("https://www.skku.edu/_attach/image/missing.jpg").respond(404)
        html = '<img src="https://www.skku.edu/_attach/image/missing.jpg">'
        result = await verify_notice_images(html, SOURCE_URL)
        assert result.checked == 1
        assert result.broken == ["https://www.skku.edu/_attach/image/missing.jpg"]

    @respx.mock
    async def test_sends_referer_header_from_source_url(self):
        # Capture the request to inspect headers
        route = respx.head("https://www.skku.edu/_attach/image/a.jpg").respond(200)
        html = '<img src="https://www.skku.edu/_attach/image/a.jpg">'
        await verify_notice_images(html, SOURCE_URL)
        assert route.called
        request = route.calls[0].request
        assert request.headers["Referer"] == SOURCE_URL

    @respx.mock
    async def test_skips_data_uris(self):
        html = '<img src="data:image/png;base64,iVBORw0KGgo=">'
        result = await verify_notice_images(html, SOURCE_URL)
        assert result.checked == 0
        assert result.broken == []

    @respx.mock
    async def test_skips_relative_urls_already_baked(self):
        # If a relative URL slipped through normalization, we don't try
        # to verify it (no base to resolve against here).
        html = '<img src="/_attach/foo.jpg">'
        result = await verify_notice_images(html, SOURCE_URL)
        # Skipped, not counted as broken
        assert result.checked == 0
        assert result.broken == []

    @respx.mock
    async def test_network_error_treated_as_broken(self):
        respx.head("https://www.skku.edu/_attach/image/x.jpg").mock(
            side_effect=httpx.ConnectError("boom")
        )
        html = '<img src="https://www.skku.edu/_attach/image/x.jpg">'
        result = await verify_notice_images(html, SOURCE_URL)
        assert result.checked == 1
        assert result.broken == ["https://www.skku.edu/_attach/image/x.jpg"]

    @respx.mock
    async def test_mixed_results(self):
        respx.head("https://www.skku.edu/a.jpg").respond(200)
        respx.head("https://www.skku.edu/b.jpg").respond(404)
        respx.head("https://www.skku.edu/c.jpg").respond(200)
        html = (
            '<img src="https://www.skku.edu/a.jpg">'
            '<img src="https://www.skku.edu/b.jpg">'
            '<img src="https://www.skku.edu/c.jpg">'
        )
        result = await verify_notice_images(html, SOURCE_URL)
        assert result.checked == 3
        assert result.broken == ["https://www.skku.edu/b.jpg"]
