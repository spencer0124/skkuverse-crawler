from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from skkuverse_crawler.core.events import NoticeCrawled, NoticeUnchanged
from skkuverse_crawler.core.ports import Outcome, SeenRecord
from skkuverse_crawler.core.results import SourceResult as DeptResult
from skkuverse_crawler.modules.notices.models import NoticeDetail, NoticeListItem
from skkuverse_crawler.modules.notices.orchestrator import (
    _process_page_full,
    _process_page_smart,
)
from tests.support.ports import RecordingSink


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

    async def test_smart_skips_before_floor_date(self):
        item = _make_item(date="2025-12-15")  # floor date 이전
        strategy = AsyncMock()
        sink = RecordingSink()
        result = DeptResult()
        logger = MagicMock()

        await _process_page_smart([item], {}, strategy, MOCK_DEPT, sink, result, logger)

        assert result.skipped == 1
        strategy.crawl_detail.assert_not_awaited()
        assert sink.events == []

    @patch("skkuverse_crawler.modules.notices.orchestrator.build_notice")
    async def test_smart_processes_after_floor_date(self, mock_build):
        item = _make_item(date="2026-04-15")
        strategy = AsyncMock()
        strategy.crawl_detail.return_value = MOCK_DETAIL
        mock_build.return_value = MagicMock(articleNo=1, sourceId="test-dept", contentHash="abc")
        sink = RecordingSink()
        result = DeptResult()
        logger = MagicMock()

        await _process_page_smart([item], {}, strategy, MOCK_DEPT, sink, result, logger)

        assert result.inserted == 1
        strategy.crawl_detail.assert_awaited_once()

    @patch("skkuverse_crawler.modules.notices.orchestrator.build_notice")
    async def test_smart_none_date_not_skipped(self, mock_build):
        """date=None은 의도적으로 통과시킴 (보수적 접근: 모르면 수집)."""
        item = _make_item(date="")  # falsy date
        strategy = AsyncMock()
        strategy.crawl_detail.return_value = MOCK_DETAIL
        mock_build.return_value = MagicMock(articleNo=1, sourceId="test-dept", contentHash="abc")
        sink = RecordingSink()
        result = DeptResult()
        logger = MagicMock()

        await _process_page_smart([item], {}, strategy, MOCK_DEPT, sink, result, logger)

        assert result.skipped == 0
        strategy.crawl_detail.assert_awaited_once()

    async def test_full_skips_before_floor_date(self):
        item = _make_item(date="2025-06-01")
        strategy = AsyncMock()
        sink = RecordingSink()
        result = DeptResult()
        logger = MagicMock()

        await _process_page_full([item], strategy, MOCK_DEPT, sink, result, logger)

        assert result.skipped == 1
        strategy.crawl_detail.assert_not_awaited()
        assert sink.events == []


class TestThreeWayBranch:
    """_process_page_smart 3-way 분기: new / changed / unchanged —
    이제 sink가 받는 이벤트가 계약이다."""

    @patch("skkuverse_crawler.modules.notices.orchestrator.build_notice")
    async def test_new_item_emits_crawled_without_change(self, mock_build):
        """not existing → NoticeCrawled(change=None); Outcome이 카운터를 결정."""
        item = _make_item(article_no=99)
        strategy = AsyncMock()
        strategy.crawl_detail.return_value = MOCK_DETAIL
        mock_build.return_value = MagicMock(articleNo=99, sourceId="test-dept", contentHash="abc")
        sink = RecordingSink(outcomes=[Outcome.INSERTED])
        result = DeptResult()
        logger = MagicMock()

        await _process_page_smart([item], {}, strategy, MOCK_DEPT, sink, result, logger)

        assert len(sink.events) == 1
        event = sink.events[0]
        assert isinstance(event, NoticeCrawled)
        assert event.source_id == "test-dept"
        assert event.change is None
        assert event.previous is None
        assert result.inserted == 1

    @patch("skkuverse_crawler.modules.notices.orchestrator.build_notice")
    async def test_none_outcome_counts_as_inserted(self, mock_build):
        """accept가 None을 돌려주면 INSERTED로 계수 — NullSink 규칙의 명문화."""
        item = _make_item(article_no=99)
        strategy = AsyncMock()
        strategy.crawl_detail.return_value = MOCK_DETAIL
        mock_build.return_value = MagicMock(articleNo=99, sourceId="test-dept", contentHash="abc")
        sink = RecordingSink()  # no scripted outcomes -> always None
        result = DeptResult()
        logger = MagicMock()

        await _process_page_smart([item], {}, strategy, MOCK_DEPT, sink, result, logger)

        assert result.inserted == 1
        assert result.updated == 0

    @patch("skkuverse_crawler.modules.notices.orchestrator.build_notice")
    async def test_updated_outcome_counts_as_updated(self, mock_build):
        item = _make_item(article_no=99)
        strategy = AsyncMock()
        strategy.crawl_detail.return_value = MOCK_DETAIL
        mock_build.return_value = MagicMock(articleNo=99, sourceId="test-dept", contentHash="abc")
        sink = RecordingSink(outcomes=[Outcome.UPDATED])
        result = DeptResult()
        logger = MagicMock()

        await _process_page_smart([item], {}, strategy, MOCK_DEPT, sink, result, logger)

        assert result.updated == 1
        assert result.inserted == 0

    @patch("skkuverse_crawler.modules.notices.orchestrator.build_notice")
    async def test_changed_item_emits_change_info(self, mock_build):
        """existing + has_changed → NoticeCrawled(previous, change) — 목록
        제목(item.title)이 new_title이어야 한다 (상세 제목 override 무관)."""
        item = _make_item(article_no=1, title="새 제목")
        existing = SeenRecord(article_no=1, title="옛 제목", date="2026-04-15", content_hash="old_hash")
        strategy = AsyncMock()
        strategy.crawl_detail.return_value = MOCK_DETAIL
        mock_build.return_value = MagicMock(articleNo=1, sourceId="test-dept", contentHash="new_hash")
        sink = RecordingSink()
        result = DeptResult()
        logger = MagicMock()

        await _process_page_smart([item], {1: existing}, strategy, MOCK_DEPT, sink, result, logger)

        assert len(sink.events) == 1
        event = sink.events[0]
        assert isinstance(event, NoticeCrawled)
        assert event.previous == existing
        change = event.change
        assert change is not None
        assert change.old_title == "옛 제목"
        assert change.new_title == "새 제목"
        assert change.title_changed is True
        assert change.old_hash == "old_hash"
        assert change.new_hash == "new_hash"
        assert change.content_changed is True
        assert result.updated == 1

    async def test_unchanged_item_emits_touch_and_flushes(self):
        """existing + not changed → NoticeUnchanged + 페이지 끝 flush 정확히 1회."""
        item = _make_item(article_no=1, title="동일 제목", date="2026-04-15")
        existing = SeenRecord(article_no=1, title="동일 제목", date="2026-04-15", content_hash="hash")
        strategy = AsyncMock()
        sink = RecordingSink()
        result = DeptResult()
        logger = MagicMock()

        await _process_page_smart([item], {1: existing}, strategy, MOCK_DEPT, sink, result, logger)

        assert result.skipped == 1
        strategy.crawl_detail.assert_not_awaited()
        assert sink.events == [
            NoticeUnchanged(source_id="test-dept", article_no=1, views=10)
        ]
        assert sink.flushes == 1

    async def test_flush_called_even_on_empty_page(self):
        """flush는 무조건 페이지 끝에서 — 빈 버퍼 no-op은 sink의 책임."""
        sink = RecordingSink()
        result = DeptResult()

        await _process_page_smart([], {}, AsyncMock(), MOCK_DEPT, sink, result, MagicMock())

        assert sink.flushes == 1
        assert sink.events == []
