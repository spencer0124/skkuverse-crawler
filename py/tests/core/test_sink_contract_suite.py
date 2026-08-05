"""The conformance suite, run against our own sinks and against liars.

Two halves, and the second is the one that matters. Passing the suite over
NullSink/JsonLinesSink/MongoSink says the tool we hand third parties works
on the implementations we ship. But a conformance suite that cannot fail
is decoration, so every rule it claims to enforce gets a sink built
specifically to break that rule.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone

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
from skkuverse_crawler.core.ports import NullSink, Outcome, SourceSpec
from skkuverse_crawler.core.sinks import JsonLinesSink
from skkuverse_crawler.core.testing import CONTRACT_SOURCE_ID, assert_sink_contract
from skkuverse_crawler.modules.notices.models import Notice
from skkuverse_crawler.plugins.mongo.sink import MongoSink

from ..support.fake_mongo import FakeCollection

# Document-mutating operations. create_index is excluded deliberately:
# prepare() is a sink's own idempotent setup and MongoSink builds its
# indexes there, which is what the suite's docstring claims and no more.
WRITE_OPS = {"update_one", "bulk_write", "find_one_and_update", "insert_one"}


SAMPLE_ARTICLE_NO = 4242


def _sample() -> ItemCrawled:
    notice = Notice(
        articleNo=SAMPLE_ARTICLE_NO,
        title="계약 테스트 공지",
        category="일반",
        author="관리자",
        department="테스트학과",
        date="2026-03-01",
        views=10,
        content="<p>본문</p>",
        contentText="본문",
        cleanHtml="<p>본문</p>",
        attachments=[],
        sourceUrl="https://example.com/4242",
        detailPath="?articleNo=4242",
        sourceId=CONTRACT_SOURCE_ID,
        crawledAt=datetime(2026, 3, 1, tzinfo=timezone.utc),
        contentHash="abc123",
    )
    return ItemCrawled(source_id=notice.sourceId, item=notice)


# ── our own sinks satisfy the suite we hand out ───────────────────────────


async def test_null_sink_conforms():
    await assert_sink_contract(NullSink(), sample=_sample(), sample_article_no=SAMPLE_ARTICLE_NO)


async def test_json_lines_sink_conforms():
    stream = io.StringIO()
    await assert_sink_contract(
        JsonLinesSink(stream), sample=_sample(), sample_article_no=SAMPLE_ARTICLE_NO
    )
    lines = stream.getvalue().splitlines()
    # The write tier really ran: a ItemCrawled line and a ContentRefreshed
    # line, and nothing from the progress tier leaked into the stream.
    assert len(lines) == 2, lines
    assert all(json.loads(line)["articleNo"] == SAMPLE_ARTICLE_NO for line in lines)


async def test_mongo_sink_conforms():
    collection = FakeCollection()
    await assert_sink_contract(
        MongoSink(collection), sample=_sample(), sample_article_no=SAMPLE_ARTICLE_NO
    )


async def test_mongo_sink_conforms_with_a_history_bearing_sample():
    """The tier-1 edit path is a different branch of accept() (it returns
    UPDATED unconditionally instead of reading upserted_id), so it gets its
    own pass rather than riding on the plain-upsert one."""
    sample = _sample()
    with_change = ItemCrawled(
        source_id=sample.source_id,
        item=sample.item,
        change=ChangeInfo(
            old_hash="old",
            new_hash="new",
            old_title="Original",
            new_title="Edited",
            title_changed=True,
            content_changed=False,
        ),
    )
    await assert_sink_contract(
        MongoSink(FakeCollection()), sample=with_change, sample_article_no=SAMPLE_ARTICLE_NO
    )


async def test_without_a_sample_nothing_is_stored():
    """The safety claim of the default call, pinned against a sink that
    would happily write. Anyone running this against a live store is
    relying on exactly this assertion."""
    collection = FakeCollection()
    await assert_sink_contract(MongoSink(collection))

    writes = [op for op in collection.ops if op[0] in WRITE_OPS]
    assert not writes, f"the sample-less contract check stored something: {writes}"


# ── and it bites when a sink lies ─────────────────────────────────────────


async def test_a_sink_missing_flush_is_rejected():
    class _NoFlush:
        async def prepare(self, source: SourceSpec) -> None:
            return None

        async def accept(self, event: CrawlEvent) -> Outcome | None:
            return None

    with pytest.raises(AssertionError, match="does not satisfy the Sink protocol"):
        await assert_sink_contract(_NoFlush())  # type: ignore[arg-type]


async def test_a_sink_that_reports_an_outcome_for_progress_is_rejected():
    """BatchCompleted stores nothing, so there is no outcome to report.
    A sink returning one is mis-signalling to the runner's aggregation."""

    class _ChattyAboutProgress(NullSink):
        async def accept(self, event: CrawlEvent) -> Outcome | None:
            if isinstance(event, BatchCompleted):
                return Outcome.UPDATED
            return None

    with pytest.raises(AssertionError, match="BatchCompleted"):
        await assert_sink_contract(_ChattyAboutProgress())


# Every event type this codebase currently defines. A sink that handles
# all of these and mishandles nothing else is correct *today* and breaks on
# the next minor release — which is the case the tolerant-reader rule
# exists for, and the only way to test it from the present.
_ALL_KNOWN_EVENTS = (
    SourceStarted,
    BatchCompleted,
    ListFetchFailed,
    SourceFinished,
    ItemFailed,
    ItemSkipped,
    ItemCrawled,
    ItemUnchanged,
    ContentRefreshed,
)


async def test_a_sink_that_answers_an_unknown_event_is_rejected():
    """The rule that lets the progress tier grow in a minor release.

    The sink below is correct for every event that exists today; it fails
    only on the one from the future. An earlier version of this test used a
    sink that answered *everything*, so it tripped on SourceStarted and the
    unknown-event rule was never actually exercised — deleting that rule
    from the shipped suite left the suite green.
    """

    class _GuessesAtTheUnknown(NullSink):
        async def accept(self, event: CrawlEvent) -> Outcome | None:
            if isinstance(event, _ALL_KNOWN_EVENTS):
                return None
            return Outcome.INSERTED  # "never heard of it, must be new"

    with pytest.raises(AssertionError, match="_UnknownFutureEvent"):
        await assert_sink_contract(_GuessesAtTheUnknown())


async def test_a_sink_that_raises_on_an_unknown_event_is_not_swallowed():
    """The commoner shape of the same mistake — `case _: raise`. The suite
    lets it propagate rather than converting it, because the traceback
    naming the sink's own line is the more useful report."""

    class _RaisesOnTheUnknown(NullSink):
        async def accept(self, event: CrawlEvent) -> Outcome | None:
            if isinstance(event, _ALL_KNOWN_EVENTS):
                return None
            raise TypeError(f"unhandled event: {type(event).__name__}")

    with pytest.raises(TypeError, match="_UnknownFutureEvent"):
        await assert_sink_contract(_RaisesOnTheUnknown())


async def test_a_sink_that_cannot_flush_an_empty_buffer_is_rejected():
    """The runner flushes on every BatchCompleted, including pages where
    nothing was buffered. A sink assuming otherwise dies on the first
    all-known page — the exception propagates rather than becoming an
    AssertionError, which is the more useful report."""

    class _AssumesNonEmpty(NullSink):
        async def flush(self) -> None:
            raise ZeroDivisionError("divided by an empty buffer")

    with pytest.raises(ZeroDivisionError):
        await assert_sink_contract(_AssumesNonEmpty())


async def test_prepare_return_values_are_deliberately_not_policed():
    """run_events never reads prepare's return, so neither does the suite.
    Asserting on it would invent a rule the runner does not have — and
    third parties would then write code to satisfy a fiction."""

    class _TalkativePrepare(NullSink):
        async def prepare(self, source: SourceSpec) -> None:
            return "ready"  # type: ignore[return-value]

    await assert_sink_contract(_TalkativePrepare())


async def test_a_sink_returning_a_bare_string_for_a_notice_is_rejected():
    """Outcome exists because the old code returned the strings
    "inserted"/"updated". A sink still doing that would be counted as
    INSERTED by the runner's `is Outcome.UPDATED` check — silently wrong
    numbers, which is worse than a crash."""

    class _LegacyStrings(NullSink):
        async def accept(self, event: CrawlEvent) -> Outcome | None:
            if isinstance(event, ItemCrawled):
                return "updated"  # type: ignore[return-value]
            return None

    with pytest.raises(AssertionError, match="expected an Outcome"):
        await assert_sink_contract(
            _LegacyStrings(), sample=_sample(), sample_article_no=SAMPLE_ARTICLE_NO
        )


async def test_a_non_notice_sample_is_rejected():
    with pytest.raises(AssertionError, match="sample must be an ItemCrawled"):
        await assert_sink_contract(
            NullSink(),
            sample=BatchCompleted(source_id="x", index=0),  # type: ignore[arg-type]
            sample_article_no=SAMPLE_ARTICLE_NO,
        )
