from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from skkuverse_crawler.notices.models import NoticeDetail, NoticeListItem
from skkuverse_crawler.notices.orchestrator import (
    DeptResult,
    _process_page_full,
    _process_page_smart,
)


def _make_item(article_no: int = 1, date: str = "2026-04-15", title: str = "제목") -> NoticeListItem:
    return NoticeListItem(
        articleNo=article_no,
        title=title,
        category="일반",
        author="관리자",
        date=date,
        views=10,
        detailPath=f"?articleNo={article_no}",
    )


MOCK_DETAIL = NoticeDetail(content="<p>본문</p>", contentText="본문", attachments=[])
MOCK_DEPT = {"id": "test-dept", "name": "테스트학과", "baseUrl": "https://example.com", "strategy": "skku-standard"}


class TestFloorDateItemSkip:
    """Floor date 이전 글은 item 레벨에서 skip."""

    @patch("skkuverse_crawler.notices.orchestrator.upsert_notice", new_callable=AsyncMock)
    @patch("skkuverse_crawler.notices.orchestrator.build_notice")
    async def test_smart_skips_before_floor_date(self, mock_build, mock_upsert, mock_collection):
        item = _make_item(date="2025-12-15")  # floor date 이전
        strategy = AsyncMock()
        result = DeptResult()
        logger = MagicMock()

        await _process_page_smart([item], {}, strategy, MOCK_DEPT, mock_collection, result, logger)

        assert result.skipped == 1
        strategy.crawl_detail.assert_not_awaited()
        mock_upsert.assert_not_awaited()

    @patch("skkuverse_crawler.notices.orchestrator.upsert_notice", new_callable=AsyncMock)
    @patch("skkuverse_crawler.notices.orchestrator.build_notice")
    async def test_smart_processes_after_floor_date(self, mock_build, mock_upsert, mock_collection):
        item = _make_item(date="2026-04-15")
        strategy = AsyncMock()
        strategy.crawl_detail.return_value = MOCK_DETAIL
        mock_build.return_value = MagicMock(articleNo=1, sourceDeptId="test-dept", contentHash="abc")
        mock_upsert.return_value = "inserted"
        result = DeptResult()
        logger = MagicMock()

        await _process_page_smart([item], {}, strategy, MOCK_DEPT, mock_collection, result, logger)

        assert result.inserted == 1
        strategy.crawl_detail.assert_awaited_once()

    @patch("skkuverse_crawler.notices.orchestrator.upsert_notice", new_callable=AsyncMock)
    @patch("skkuverse_crawler.notices.orchestrator.build_notice")
    async def test_smart_none_date_not_skipped(self, mock_build, mock_upsert, mock_collection):
        """date=None은 의도적으로 통과시킴 (보수적 접근: 모르면 수집)."""
        item = _make_item(date="")  # falsy date
        strategy = AsyncMock()
        strategy.crawl_detail.return_value = MOCK_DETAIL
        mock_build.return_value = MagicMock(articleNo=1, sourceDeptId="test-dept", contentHash="abc")
        mock_upsert.return_value = "inserted"
        result = DeptResult()
        logger = MagicMock()

        await _process_page_smart([item], {}, strategy, MOCK_DEPT, mock_collection, result, logger)

        assert result.skipped == 0
        strategy.crawl_detail.assert_awaited_once()

    @patch("skkuverse_crawler.notices.orchestrator.upsert_notice", new_callable=AsyncMock)
    @patch("skkuverse_crawler.notices.orchestrator.build_notice")
    async def test_full_skips_before_floor_date(self, mock_build, mock_upsert, mock_collection):
        item = _make_item(date="2025-06-01")
        strategy = AsyncMock()
        result = DeptResult()
        logger = MagicMock()

        await _process_page_full([item], strategy, MOCK_DEPT, mock_collection, result, logger)

        assert result.skipped == 1
        strategy.crawl_detail.assert_not_awaited()


class TestThreeWayBranch:
    """_process_page_smart 3-way 분기: new / changed / unchanged."""

    @patch("skkuverse_crawler.notices.orchestrator.bulk_touch_notices", new_callable=AsyncMock)
    @patch("skkuverse_crawler.notices.orchestrator.upsert_notice", new_callable=AsyncMock)
    @patch("skkuverse_crawler.notices.orchestrator.build_notice")
    async def test_new_item_calls_upsert(self, mock_build, mock_upsert, mock_touch, mock_collection):
        """not existing → upsert_notice."""
        item = _make_item(article_no=99)
        strategy = AsyncMock()
        strategy.crawl_detail.return_value = MOCK_DETAIL
        mock_build.return_value = MagicMock(articleNo=99, sourceDeptId="test-dept", contentHash="abc")
        mock_upsert.return_value = "inserted"
        result = DeptResult()
        logger = MagicMock()

        # existing_meta is empty → item is new
        await _process_page_smart([item], {}, strategy, MOCK_DEPT, mock_collection, result, logger)

        mock_upsert.assert_awaited_once()
        assert result.inserted == 1

    @patch("skkuverse_crawler.notices.orchestrator.bulk_touch_notices", new_callable=AsyncMock)
    @patch("skkuverse_crawler.notices.orchestrator.update_with_history", new_callable=AsyncMock)
    @patch("skkuverse_crawler.notices.orchestrator.build_notice")
    async def test_changed_item_calls_update_with_history(
        self, mock_build, mock_update_hist, mock_touch, mock_collection
    ):
        """existing + has_changed → update_with_history with source=tier1."""
        item = _make_item(article_no=1, title="새 제목")
        existing_meta = {1: {"articleNo": 1, "title": "옛 제목", "date": "2026-04-15", "contentHash": "old_hash"}}
        strategy = AsyncMock()
        strategy.crawl_detail.return_value = MOCK_DETAIL
        mock_build.return_value = MagicMock(articleNo=1, sourceDeptId="test-dept", contentHash="new_hash")
        result = DeptResult()
        logger = MagicMock()

        await _process_page_smart([item], existing_meta, strategy, MOCK_DEPT, mock_collection, result, logger)

        mock_update_hist.assert_awaited_once()
        edit_entry = mock_update_hist.call_args[0][2]
        assert edit_entry["source"] == "tier1"
        assert edit_entry["oldTitle"] == "옛 제목"
        assert edit_entry["newTitle"] == "새 제목"
        assert result.updated == 1

    @patch("skkuverse_crawler.notices.orchestrator.bulk_touch_notices", new_callable=AsyncMock)
    async def test_unchanged_item_goes_to_touch(self, mock_touch, mock_collection):
        """existing + not changed → bulk_touch_notices."""
        item = _make_item(article_no=1, title="동일 제목", date="2026-04-15")
        existing_meta = {1: {"articleNo": 1, "title": "동일 제목", "date": "2026-04-15", "contentHash": "hash"}}
        strategy = AsyncMock()
        result = DeptResult()
        logger = MagicMock()

        await _process_page_smart([item], existing_meta, strategy, MOCK_DEPT, mock_collection, result, logger)

        assert result.skipped == 1
        strategy.crawl_detail.assert_not_awaited()
        mock_touch.assert_awaited_once()
        touch_items = mock_touch.call_args[0][1]
        assert len(touch_items) == 1
        assert touch_items[0]["articleNo"] == 1
