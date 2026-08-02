"""The three ports of the crawl seam (adr-006 결정 ②).

Core knows only these protocols; plugins implement them. Infra-free by
contract — importing this module must never pull in motor/pymongo
(pinned by tests/structure test_core_import_is_infra_free).
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .events import CrawlEvent


@dataclass(frozen=True)
class SeenRecord:
    """What SeenIndex.lookup returns per known article.

    content_hash defaults to None because stored documents may pre-date
    hashing — a required field would turn key absence into a mid-crawl
    TypeError silently counted as an item error (plan 위험 ⑥).
    """

    article_no: int
    title: str
    date: str
    content_hash: str | None = None


@dataclass(frozen=True)
class DetailRef:
    """A pointer to a detail page the store wants re-fetched."""

    article_no: int
    detail_path: str = ""


@dataclass(frozen=True)
class SourceSpec:
    """Identity of the source a sink is asked to prepare for.

    The Mongo sink's indexes are collection-global, so it ignores this
    beyond an idempotence guard; the argument exists for sinks with real
    per-source setup (table-per-source, file-per-source).
    """

    source_id: str
    name: str = ""


class Outcome(enum.Enum):
    """Sink verdict for a write-bearing event. Values inherit the strings
    upsert_notice historically returned."""

    INSERTED = "inserted"
    UPDATED = "updated"


@runtime_checkable
class SeenIndex(Protocol):
    async def lookup(
        self, source_id: str, article_nos: Sequence[int]
    ) -> Mapping[int, SeenRecord]: ...


@runtime_checkable
class WorkSeed(Protocol):
    async def pending_refs(self, source_id: str) -> Sequence[DetailRef]: ...


@runtime_checkable
class Notifier(Protocol):
    """Outbound operator notification (architecture ownership table —
    plugins/health depends on this, never on plugins/discord directly).

    Returns True when delivered. Implementations must not raise: callers
    sit on never-fail paths (the post-crawl health hook)."""

    async def notify(self, content: str) -> bool: ...


@runtime_checkable
class Sink(Protocol):
    async def prepare(self, source: SourceSpec) -> None: ...

    async def accept(self, event: CrawlEvent) -> Outcome | None: ...

    async def flush(self) -> None: ...


class NullSink:
    """Discards everything. accept returning None means INSERTED to the
    caller's counters (architecture §러너 집계 규칙)."""

    async def prepare(self, source: SourceSpec) -> None:
        return None

    async def accept(self, event: CrawlEvent) -> Outcome | None:
        return None

    async def flush(self) -> None:
        return None


class NullWorkSeed:
    async def pending_refs(self, source_id: str) -> Sequence[DetailRef]:
        return ()


@dataclass(frozen=True)
class Ports:
    """Port bundle handed to run_crawl. All-defaults: `Ports()` is the
    plugin-less configuration. The seen index lives in CrawlMode
    (Incremental(seen) | FullSweep — core/crawl.py), not here."""

    sink: Sink = field(default_factory=NullSink)
    work_seed: WorkSeed = field(default_factory=NullWorkSeed)
