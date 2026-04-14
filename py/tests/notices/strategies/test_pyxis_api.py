from __future__ import annotations

import json
from unittest.mock import AsyncMock

from skkuverse_crawler.notices.strategies.pyxis_api import PyxisApiStrategy


BASE_CONFIG = {
    "id": "lib-hssc",
    "name": "도서관(인사캠/중앙학술정보관)",
    "strategy": "pyxis-api",
    "baseUrl": "https://lib.skku.edu/pyxis-api/1",
    "bulletinBoardId": 1,
    "bulletinCategoryId": 2,
    "pagination": {"type": "offset", "param": "offset", "limit": 10},
}


def _list_response(
    bulletins: list[dict],
    total_count: int | None = None,
    offset: int = 0,
    max_: int = 10,
) -> str:
    return json.dumps({
        "success": True,
        "code": "success.retrieved",
        "message": "조회되었습니다.",
        "data": {
            "totalCount": total_count if total_count is not None else len(bulletins),
            "offset": offset,
            "max": max_,
            "list": bulletins,
        },
    })


def _detail_response(content: str, attachments: list[dict] | None = None) -> str:
    return json.dumps({
        "success": True,
        "code": "success.retrieved",
        "message": "조회되었습니다.",
        "data": {
            "id": 12345,
            "title": "테스트 공지",
            "content": content,
            "attachments": attachments or [],
            "worker": {"name": "테****관"},
            "dateCreated": "2026-04-13 10:00:00",
        },
    })


SAMPLE_BULLETIN = {
    "id": 12345,
    "title": "테스트 공지사항",
    "bulletinCategory": {"id": 2, "name": "중앙"},
    "writer": "중****관",
    "dateCreated": "2026-04-13 10:21:43",
    "hitCnt": 42,
    "attachmentCnt": 1,
    "attachments": [
        {
            "id": 900,
            "physicalName": "abc-def-123",
            "logicalName": "안내문.pdf",
            "fileType": "application/pdf",
            "fileSize": 12345,
            "originalImageUrl": "/attachments/BULLETIN/abc-def-123",
        }
    ],
}


async def test_crawl_list_basic():
    fetcher = AsyncMock()
    fetcher.fetch.return_value = _list_response([SAMPLE_BULLETIN])
    strategy = PyxisApiStrategy(fetcher)

    items = await strategy.crawl_list(BASE_CONFIG, page=0)

    assert len(items) == 1
    item = items[0]
    assert item.articleNo == 12345
    assert item.title == "테스트 공지사항"
    assert item.category == "중앙"
    assert item.author == "중****관"
    assert item.date == "2026-04-13"
    assert item.views == 42
    assert "12345" in item.detailPath


async def test_crawl_list_category_filter_in_url():
    fetcher = AsyncMock()
    fetcher.fetch.return_value = _list_response([])
    strategy = PyxisApiStrategy(fetcher)

    await strategy.crawl_list(BASE_CONFIG, page=0)

    called_url = fetcher.fetch.call_args[0][0]
    assert "bulletinCategoryId=2" in called_url


async def test_crawl_list_no_category_filter():
    config = {**BASE_CONFIG, "bulletinCategoryId": 0}
    fetcher = AsyncMock()
    fetcher.fetch.return_value = _list_response([])
    strategy = PyxisApiStrategy(fetcher)

    await strategy.crawl_list(config, page=0)

    called_url = fetcher.fetch.call_args[0][0]
    assert "bulletinCategoryId" not in called_url


async def test_crawl_list_empty_when_past_total():
    fetcher = AsyncMock()
    fetcher.fetch.return_value = _list_response([], total_count=5, offset=10)
    strategy = PyxisApiStrategy(fetcher)

    items = await strategy.crawl_list(BASE_CONFIG, page=1)

    assert items == []


async def test_crawl_list_offset_calculation():
    fetcher = AsyncMock()
    fetcher.fetch.return_value = _list_response([], total_count=50)
    strategy = PyxisApiStrategy(fetcher)

    await strategy.crawl_list(BASE_CONFIG, page=2)

    called_url = fetcher.fetch.call_args[0][0]
    assert "offset=20" in called_url


async def test_crawl_list_null_category():
    bulletin = {**SAMPLE_BULLETIN, "bulletinCategory": None}
    fetcher = AsyncMock()
    fetcher.fetch.return_value = _list_response([bulletin])
    strategy = PyxisApiStrategy(fetcher)

    items = await strategy.crawl_list(BASE_CONFIG, page=0)

    assert items[0].category == ""


async def test_crawl_detail_basic():
    fetcher = AsyncMock()
    fetcher.fetch.return_value = _detail_response(
        "<p>공지 내용입니다.</p>",
        [{"logicalName": "첨부.pdf", "originalImageUrl": "/attachments/BULLETIN/xyz"}],
    )
    strategy = PyxisApiStrategy(fetcher)

    detail = await strategy.crawl_detail(
        {"articleNo": 99999, "detailPath": ""}, BASE_CONFIG
    )

    assert detail is not None
    assert "공지 내용입니다" in detail.contentText
    assert "<p>" in detail.content


async def test_crawl_detail_uses_cached_attachments():
    """Attachments cached from list (with physicalName) are preferred over detail."""
    fetcher = AsyncMock()
    # First: crawl_list to populate cache
    fetcher.fetch.return_value = _list_response([SAMPLE_BULLETIN])
    strategy = PyxisApiStrategy(fetcher)
    await strategy.crawl_list(BASE_CONFIG, page=0)

    # Then: crawl_detail — should use cached attachments
    fetcher.fetch.return_value = _detail_response("<p>내용</p>", [])
    detail = await strategy.crawl_detail(
        {"articleNo": 12345, "detailPath": ""}, BASE_CONFIG
    )

    assert detail is not None
    assert len(detail.attachments) == 1
    assert detail.attachments[0]["name"] == "안내문.pdf"
    assert "abc-def-123" in detail.attachments[0]["url"]


async def test_crawl_detail_fallback_original_image_url():
    """When physicalName is missing, use originalImageUrl for URL construction."""
    fetcher = AsyncMock()
    fetcher.fetch.return_value = _detail_response(
        "<p>내용</p>",
        [{"logicalName": "파일.pdf", "originalImageUrl": "/attachments/BULLETIN/uuid-123"}],
    )
    strategy = PyxisApiStrategy(fetcher)

    detail = await strategy.crawl_detail(
        {"articleNo": 77777, "detailPath": ""}, BASE_CONFIG
    )

    assert detail is not None
    assert len(detail.attachments) == 1
    assert "uuid-123" in detail.attachments[0]["url"]
    assert detail.attachments[0]["url"].startswith("https://lib.skku.edu/pyxis-api")


async def test_crawl_detail_api_error():
    fetcher = AsyncMock()
    fetcher.fetch.side_effect = Exception("Connection timeout")
    strategy = PyxisApiStrategy(fetcher)

    detail = await strategy.crawl_detail(
        {"articleNo": 12345, "detailPath": ""}, BASE_CONFIG
    )

    assert detail is None


async def test_crawl_list_api_error_returns_empty():
    fetcher = AsyncMock()
    fetcher.fetch.side_effect = Exception("Server error")
    strategy = PyxisApiStrategy(fetcher)

    items = await strategy.crawl_list(BASE_CONFIG, page=0)

    assert items == []


async def test_crawl_list_unsuccessful_response():
    fetcher = AsyncMock()
    fetcher.fetch.return_value = json.dumps({"success": False, "code": "error", "data": None})
    strategy = PyxisApiStrategy(fetcher)

    items = await strategy.crawl_list(BASE_CONFIG, page=0)

    assert items == []
