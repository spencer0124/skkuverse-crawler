"""Test doubles for the core ports.

NullSeenIndex lives HERE, not in core — adr-006 v2 demoted it from a core
default to a test stub (a Null that *induces* incremental-vs-full behavior
is an emergence risk; CrawlMode owns that decision from PR 6).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from skkuverse_crawler.core.events import CrawlEvent, ItemCrawled
from skkuverse_crawler.core.ports import DetailRef, Outcome, SeenRecord, SourceSpec


class NullSeenIndex:
    async def lookup(
        self, source_id: str, article_nos: Sequence[int]
    ) -> Mapping[int, SeenRecord]:
        return {}


class RecordingSink:
    """Captures the runner↔sink conversation for assertions.

    outcomes: optional script of accept() return values, consumed in
    order but ONLY for ItemCrawled — the sole event whose outcome the
    runner reads. Progress events flow through accept uniformly and must
    not eat the script. Exhausted/omitted script ⇒ None ⇒ the runner
    counts INSERTED.
    """

    def __init__(self, outcomes: Sequence[Outcome | None] = ()) -> None:
        self.events: list[CrawlEvent] = []
        self.prepared: list[SourceSpec] = []
        self.flushes = 0
        self._outcomes = list(outcomes)

    async def prepare(self, source: SourceSpec) -> None:
        self.prepared.append(source)

    async def accept(self, event: CrawlEvent) -> Outcome | None:
        self.events.append(event)
        if self._outcomes and isinstance(event, ItemCrawled):
            return self._outcomes.pop(0)
        return None

    async def flush(self) -> None:
        self.flushes += 1


__all__ = ["DetailRef", "NullSeenIndex", "RecordingSink"]
