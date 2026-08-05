"""iter_source event-stream tests.

The generator is the crawl loop's public shape from PR 6 on: these pin the
event sequences and SourceFinished.stopped_by per scenario (위험 ③'s
"시나리오별 stopped_by 단언"), plus the two log-ordering traps the goldens
also pin (early-stop log before processing; floor log once per exit).
Fixture-router/system-level paths stay covered by the characterization
goldens — here strategies are scripted AsyncMocks for speed and precision.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from structlog.testing import capture_logs

from skkuverse_crawler.core.crawl import FullSweep, Incremental
from skkuverse_crawler.core.events import (
    BatchCompleted,
    ContentRefreshed,
    CrawlEvent,
    ItemCrawled,
    ItemFailed,
    ItemSkipped,
    ItemUnchanged,
    ListFetchFailed,
    SourceFinished,
    SourceStarted,
)
from skkuverse_crawler.core.ports import DetailRef, NullWorkSeed, SeenRecord
from skkuverse_crawler.modules.notices.models import NoticeDetail, NoticeListItem
from skkuverse_crawler.modules.notices.orchestrator import CrawlOptions, iter_source
from tests.support.ports import NullSeenIndex


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


class _MetaSeen:
    """SeenIndex stub returning one fixed meta for every lookup."""

    def __init__(self, meta: dict[int, SeenRecord]) -> None:
        self._meta = meta

    async def lookup(self, source_id, article_nos):
        return {no: rec for no, rec in self._meta.items() if no in article_nos}


def _strategy(pages: list, detail: NoticeDetail | Exception = MOCK_DETAIL) -> AsyncMock:
    strategy = AsyncMock()
    strategy.crawl_list.side_effect = pages
    if isinstance(detail, Exception):
        strategy.crawl_detail.side_effect = detail
    else:
        strategy.crawl_detail.return_value = detail
    return strategy


async def _collect(
    strategy: AsyncMock,
    *,
    mode=FullSweep(),
    work_seed=NullWorkSeed(),
    options: CrawlOptions | None = None,
) -> list[CrawlEvent]:
    return [
        ev
        async for ev in iter_source(
            MOCK_DEPT,
            strategy,
            mode=mode,
            work_seed=work_seed,
            options=options or CrawlOptions(),
            logger=MagicMock(),
        )
    ]


def _types(events: list[CrawlEvent]) -> list[type]:
    return [type(ev) for ev in events]


def _finished(events: list[CrawlEvent]) -> SourceFinished:
    assert isinstance(events[-1], SourceFinished)
    return events[-1]


class TestStopScenarios:
    async def test_empty_first_page(self):
        events = await _collect(_strategy([[]]))
        assert _types(events) == [SourceStarted, SourceFinished]
        assert _finished(events).stopped_by == "empty_page"

    async def test_two_pages_then_empty(self):
        pages = [[_make_item(1)], [_make_item(2)], []]
        events = await _collect(_strategy(pages))
        assert _types(events) == [
            SourceStarted,
            ItemCrawled, BatchCompleted,
            ItemCrawled, BatchCompleted,
            SourceFinished,
        ]
        assert _finished(events).stopped_by == "empty_page"

    async def test_floor_page1_stops_before_processing(self):
        strategy = _strategy([[_make_item(1)], [_make_item(2, date="2025-12-01")]])
        events = await _collect(strategy, mode=Incremental(NullSeenIndex()))
        assert _types(events) == [
            SourceStarted, ItemCrawled, BatchCompleted, SourceFinished,
        ]
        assert _finished(events).stopped_by == "floor_date"
        # Page-1 item never got a detail fetch — the pre-process break.
        assert strategy.crawl_detail.await_count == 1

    async def test_floor_page0_processes_pinned_then_stops(self):
        pinned = _make_item(99, date="2026-05-01")
        pinned.pinned = True
        old = _make_item(1, date="2025-12-01")
        events = await _collect(_strategy([[pinned, old]]))
        assert _types(events) == [
            SourceStarted, ItemCrawled, ItemSkipped, BatchCompleted, SourceFinished,
        ]
        skipped = events[2]
        assert isinstance(skipped, ItemSkipped)
        assert skipped.article_no == 1
        assert skipped.reason == "below_floor"
        assert _finished(events).stopped_by == "floor_date"

    async def test_all_known_page1_stops(self):
        known = SeenRecord(article_no=2, title="제목", date="2026-04-15")
        strategy = _strategy([[_make_item(1)], [_make_item(2)]])
        events = await _collect(strategy, mode=Incremental(_MetaSeen({2: known})))
        assert _types(events) == [
            SourceStarted, ItemCrawled, BatchCompleted, SourceFinished,
        ]
        assert _finished(events).stopped_by == "all_known"

    async def test_all_known_first_page_processes_then_stops(self):
        known = SeenRecord(article_no=1, title="제목", date="2026-04-15")
        strategy = _strategy([[_make_item(1)]])
        events = await _collect(strategy, mode=Incremental(_MetaSeen({1: known})))
        assert _types(events) == [
            SourceStarted, ItemUnchanged, BatchCompleted, SourceFinished,
        ]
        assert _finished(events).stopped_by == "all_known_first_page"

    async def test_fetch_fail_page0_marks_source_down(self):
        events = await _collect(_strategy([ConnectionError("refused")]))
        assert _types(events) == [SourceStarted, ListFetchFailed, SourceFinished]
        finished = _finished(events)
        assert finished.stopped_by == "list_fetch_failed"
        assert finished.source_down is True
        assert "refused" in finished.last_error

    async def test_fetch_fail_page1_not_source_down(self):
        events = await _collect(_strategy([[_make_item(1)], ConnectionError("refused")]))
        assert _types(events) == [
            SourceStarted, ItemCrawled, BatchCompleted, ListFetchFailed, SourceFinished,
        ]
        finished = _finished(events)
        assert finished.stopped_by == "list_fetch_failed"
        assert finished.source_down is False
        assert finished.last_error == ""

    async def test_max_pages_exhaustion(self):
        events = await _collect(
            _strategy([[_make_item(1)]]), options=CrawlOptions(max_pages=1)
        )
        assert _types(events) == [
            SourceStarted, ItemCrawled, BatchCompleted, SourceFinished,
        ]
        assert _finished(events).stopped_by == "max_pages"

    async def test_incremental_cold_start_continues(self):
        """위험 ⑧ pin: Incremental + empty index (meta={}) is a normal cold
        start — the first page MUST be processed, not early-stopped. The
        should_continue docstring and the golden cold run cross-reference
        this behavior."""
        events = await _collect(
            _strategy([[_make_item(1)], []]), mode=Incremental(NullSeenIndex())
        )
        assert ItemCrawled in _types(events)
        assert _finished(events).stopped_by == "empty_page"


class TestBackfill:
    async def test_refreshed_events_precede_pages(self):
        work_seed = AsyncMock()
        work_seed.pending_refs.return_value = [DetailRef(article_no=7, detail_path="?articleNo=7")]
        events = await _collect(_strategy([[]]), work_seed=work_seed)
        assert _types(events) == [SourceStarted, ContentRefreshed, SourceFinished]
        refreshed = events[1]
        assert isinstance(refreshed, ContentRefreshed)
        assert refreshed.ref.article_no == 7
        assert sorted(refreshed.fields) == [
            "attachments", "cleanHtml", "cleanMarkdown",
            "content", "contentHash", "contentText",
        ]


class TestItemBranches:
    """3-way item branch as event payloads (ports of the sink-era tests)."""

    @patch("skkuverse_crawler.modules.notices.orchestrator.build_notice")
    async def test_new_item_yields_crawled_without_change(self, mock_build):
        mock_build.return_value = MagicMock(articleNo=1, sourceId="test-dept", contentHash="abc")
        events = await _collect(_strategy([[_make_item(1)], []]))
        crawled = events[1]
        assert isinstance(crawled, ItemCrawled)
        assert crawled.source_id == "test-dept"
        assert crawled.change is None
        assert crawled.previous is None

    @patch("skkuverse_crawler.modules.notices.orchestrator.build_notice")
    async def test_changed_item_carries_change_info(self, mock_build):
        """new_title must be the LIST title (detail pages may override)."""
        existing = SeenRecord(article_no=1, title="옛 제목", date="2026-04-15", content_hash="old_hash")
        mock_build.return_value = MagicMock(articleNo=1, sourceId="test-dept", contentHash="new_hash")
        strategy = _strategy([[_make_item(1, title="새 제목")]])
        events = await _collect(strategy, mode=Incremental(_MetaSeen({1: existing})))
        crawled = events[1]
        assert isinstance(crawled, ItemCrawled)
        assert crawled.previous == existing
        change = crawled.change
        assert change is not None
        assert change.old_title == "옛 제목"
        assert change.new_title == "새 제목"
        assert change.title_changed is True
        assert change.old_hash == "old_hash"
        assert change.new_hash == "new_hash"
        assert change.content_changed is True

    async def test_unchanged_item_yields_touch(self):
        existing = SeenRecord(article_no=1, title="동일 제목", date="2026-04-15", content_hash="h")
        strategy = _strategy([[_make_item(1, title="동일 제목")]])
        events = await _collect(strategy, mode=Incremental(_MetaSeen({1: existing})))
        touch = events[1]
        assert isinstance(touch, ItemUnchanged)
        assert touch.article_no == 1
        assert touch.fields == {"views": 10}
        strategy.crawl_detail.assert_not_awaited()

    async def test_item_exception_yields_failed_and_continues(self):
        strategy = _strategy(
            [[_make_item(1), _make_item(2)], []],
            detail=RuntimeError("detail exploded"),
        )
        events = await _collect(strategy)
        assert _types(events) == [
            SourceStarted, ItemFailed, ItemFailed, BatchCompleted, SourceFinished,
        ]
        failed = events[1]
        assert isinstance(failed, ItemFailed)
        assert "detail exploded" in failed.error


class TestLogOrderPins:
    """The two golden log-order traps, pinned independently of snapshots."""

    async def test_early_stop_logged_before_processing(self):
        existing = SeenRecord(article_no=1, title="옛 제목", date="2026-04-15", content_hash="old")
        strategy = _strategy([[_make_item(1, title="새 제목")]])
        with capture_logs() as logs:
            async for _ in iter_source(
                MOCK_DEPT, strategy, mode=Incremental(_MetaSeen({1: existing})),
                work_seed=NullWorkSeed(), options=CrawlOptions(),
            logger=_structlog_logger()):
                pass
        names = [entry["event"] for entry in logs]
        assert names.index("all_known_first_page_early_stop") < names.index("change_detected")

    async def test_floor_log_exactly_once_per_exit(self):
        strategy = _strategy([[_make_item(1)], [_make_item(2, date="2025-12-01")]])
        with capture_logs() as logs:
            async for _ in iter_source(
                MOCK_DEPT, strategy, mode=Incremental(NullSeenIndex()),
                work_seed=NullWorkSeed(), options=CrawlOptions(),
            logger=_structlog_logger()):
                pass
        names = [entry["event"] for entry in logs]
        assert names.count("floor_date_stopping") == 1


def _structlog_logger():
    from skkuverse_crawler.shared.logger import get_logger

    return get_logger("test_orchestrator")
