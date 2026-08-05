"""run_events — the aggregation table as executable contract."""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator, Iterable

import pytest

from skkuverse_crawler.core.events import (
    BatchCompleted,
    ChangeInfo,
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
from skkuverse_crawler.core.ports import DetailRef, Outcome
from skkuverse_crawler.core.results import SourceResult
from skkuverse_crawler.core.runner import run_events
from tests.support.ports import RecordingSink


async def _stream(events: Iterable[CrawlEvent]) -> AsyncIterator[CrawlEvent]:
    for event in events:
        yield event


def _crawled(change: ChangeInfo | None = None) -> ItemCrawled:
    return ItemCrawled(source_id="s", item=object(), change=change)


def _change() -> ChangeInfo:
    return ChangeInfo(
        old_hash="a", new_hash="b", old_title="o", new_title="n",
        title_changed=True, content_changed=True,
    )


async def _run(events: Iterable[CrawlEvent], sink: RecordingSink) -> SourceResult:
    return await run_events(_stream(events), sink, result=SourceResult(source_id="s"))


class TestAggregationTable:
    async def test_crawled_outcome_drives_counters(self):
        sink = RecordingSink(outcomes=[Outcome.INSERTED, Outcome.UPDATED])
        result = await _run([_crawled(), _crawled()], sink)
        assert (result.inserted, result.updated) == (1, 1)

    async def test_crawled_none_outcome_counts_inserted(self):
        result = await _run([_crawled()], RecordingSink())
        assert result.inserted == 1

    async def test_changed_crawled_is_outcome_driven_too(self):
        """The documented PR 6 delta, pinned on purpose: a None-returning
        sink counts a changed ItemCrawled as INSERTED (the old inline
        loop counted updated unconditionally; MongoSink returns UPDATED on
        the history path so production totals are unchanged)."""
        result = await _run([_crawled(change=_change())], RecordingSink())
        assert result.inserted == 1
        assert result.updated == 0

    async def test_content_refreshed_counts_updated_ignoring_outcome(self):
        event = ContentRefreshed(source_id="s", ref=DetailRef(article_no=1), fields={})
        result = await _run([event], RecordingSink())
        assert result.updated == 1

    async def test_unchanged_and_skipped_count_skipped(self):
        events = [
            ItemUnchanged(source_id="s", article_no=1, fields={"views": 0}),
            ItemSkipped(source_id="s", article_no=2, reason="below_floor"),
        ]
        result = await _run(events, RecordingSink())
        assert result.skipped == 2

    async def test_failures_count_errors(self):
        events = [
            ItemFailed(source_id="s", article_no=1, error="boom"),
            ListFetchFailed(source_id="s", page=3, error="net"),
        ]
        result = await _run(events, RecordingSink())
        assert result.errors == 2

    async def test_page_completed_flushes_each_time(self):
        sink = RecordingSink()
        await _run(
            [BatchCompleted(source_id="s", index=0), BatchCompleted(source_id="s", index=1)],
            sink,
        )
        assert sink.flushes == 2

    async def test_source_finished_stamps_result(self):
        event = SourceFinished(
            source_id="s", stopped_by="list_fetch_failed",
            source_down=True, last_error="refused",
        )
        result = await _run([event], RecordingSink())
        assert result.source_down is True
        assert result.last_error == "refused"
        assert result.duration_ms >= 0

    async def test_started_and_unknown_events_accepted_but_uncounted(self):
        @dataclasses.dataclass(frozen=True)
        class _FutureEvent(CrawlEvent):
            payload: str = "?"

        sink = RecordingSink()
        result = await _run(
            [SourceStarted(source_id="s", source_name="n"), _FutureEvent(source_id="s")],
            sink,
        )
        assert len(sink.events) == 2  # uniform accept — every event reaches the sink
        assert (result.inserted, result.updated, result.skipped, result.errors) == (0, 0, 0, 0)


class TestFlushFailureContract:
    async def test_flush_exception_propagates(self):
        """adr-006 §⑪: a flush failure aborts the source — run_events must
        not swallow it into errors."""

        class _ExplodingFlushSink(RecordingSink):
            async def flush(self) -> None:
                raise RuntimeError("bulk_write down")

        with pytest.raises(RuntimeError, match="bulk_write down"):
            await _run([BatchCompleted(source_id="s", index=0)], _ExplodingFlushSink())
