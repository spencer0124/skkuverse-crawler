"""Generic event runner — the aggregation table as code (architecture §집계).

Every event flows to sink.accept uniformly (the v1 "ItemSkipped skips the
sink" special case is abolished; sinks are tolerant readers and ignore
what they don't know). Aggregation is independent of sink returns except
NoticeCrawled, whose Outcome decides inserted/updated — None ⇒ INSERTED.

PageCompleted → sink.flush() runs UNGUARDED on purpose: a flush failure
must propagate and abort the source (adr-006 §⑪ — 현행 의미가 계약).

The event match ends in `case _: pass`, NOT assert_never: the event space
is open (progress tier grows in minor releases), so an unknown event is
accepted, uncounted, and ignored.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

from .events import (
    ContentRefreshed,
    CrawlEvent,
    ItemFailed,
    ItemSkipped,
    ListFetchFailed,
    NoticeCrawled,
    NoticeUnchanged,
    PageCompleted,
    SourceFinished,
)
from .ports import Outcome, Sink
from .results import SourceResult


async def run_events(
    events: AsyncIterator[CrawlEvent],
    sink: Sink,
    *,
    result: SourceResult,
) -> SourceResult:
    """Drive an event stream into a sink and aggregate a SourceResult.

    The caller constructs `result` (source identity is caller knowledge);
    it is mutated in place and returned.
    """
    started = time.monotonic()
    async for event in events:
        outcome = await sink.accept(event)
        match event:
            case NoticeCrawled():
                if outcome is Outcome.UPDATED:
                    result.updated += 1
                else:
                    result.inserted += 1
            case ContentRefreshed():
                # Table addendum: outcome ignored, counted as updated —
                # today's backfill semantics.
                result.updated += 1
            case NoticeUnchanged() | ItemSkipped():
                result.skipped += 1
            case ItemFailed() | ListFetchFailed():
                result.errors += 1
            case PageCompleted():
                await sink.flush()
            case SourceFinished(source_down=source_down, last_error=last_error):
                result.source_down = source_down
                result.last_error = last_error
                result.duration_ms = int((time.monotonic() - started) * 1000)
            case _:
                pass
    return result
