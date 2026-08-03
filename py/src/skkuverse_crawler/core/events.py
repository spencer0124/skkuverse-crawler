"""Crawl event vocabulary — two tiers (adr-006 결정 ⑧).

Result tier is the stable API: adding or changing one is a MAJOR version
event once published. Progress tier may grow in minor releases. Sinks are
tolerant readers: unknown events are silently ignored (``case _: return
None``) — pinned by the sink contract test.

Events are frozen but may hold mutable payloads (Notice carries lists),
so they are not hashable in practice; nothing hashes events.

In PR 5 only the write-bearing result events (NoticeCrawled,
NoticeUnchanged, ContentRefreshed) are emitted by the inline loop; the
rest are declared ahead of PR 6's generator, which owns full emission.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .ports import DetailRef, SeenRecord

if TYPE_CHECKING:
    # Type-only reverse-layer edge (core → modules), sanctioned until
    # Notice's final home is settled (PR 6/7). Must stay type-only.
    from ..modules.notices.models import Notice


@dataclass(frozen=True)
class CrawlEvent:
    """Base of all events. Self-contained — a sink must be able to act on
    one event alone; remembering earlier events would make the sink
    stateful and unsafe under parallel crawls (adr-006 §⑧)."""

    source_id: str


@dataclass(frozen=True)
class ChangeInfo:
    """Exactly what the tier-1 edit_entry needs from the module side.

    new_title is the LIST-page title (detail pages may override the
    stored title, and the stored edit history pins the list value).
    detectedAt, "source": "tier1", and the $push/$slice mechanics are the
    Mongo sink's business.
    """

    old_hash: str | None
    new_hash: str | None
    old_title: str
    new_title: str
    title_changed: bool
    content_changed: bool


# ── result tier (stable API; add/change = major) ──────────────────────────


@dataclass(frozen=True)
class NoticeCrawled(CrawlEvent):
    """A fetched notice ready to store. change=None means a new item
    (plain upsert); a populated change means a tier-1 detected edit
    (history-preserving update)."""

    notice: Notice
    previous: SeenRecord | None = None
    change: ChangeInfo | None = None


@dataclass(frozen=True)
class NoticeUnchanged(CrawlEvent):
    """A known, unmodified item — the sink batches these and emits one
    bulk touch per flush (crawledAt/views refresh; plan 위험 ②)."""

    article_no: int
    views: int


@dataclass(frozen=True)
class ContentRefreshed(CrawlEvent):
    """Null-content backfill result. ``fields`` is an explicit payload,
    deliberately NOT the upsert path (plan 위험 ④).

    What ④ warns against is routing backfill through *build_notice* — that
    would rewrite editHistory and every unrelated field on documents whose
    only problem was a missing body. It does share the content **pipeline**
    with the crawl, and must: deriving these fields separately is what let
    a backfilled notice disagree with a crawled one and made the Tier-2
    checker "detect" an edit on it every pass."""

    ref: DetailRef
    fields: Mapping[str, Any]


@dataclass(frozen=True)
class ItemFailed(CrawlEvent):
    article_no: int
    error: str


@dataclass(frozen=True)
class ItemSkipped(CrawlEvent):
    article_no: int
    reason: str


# ── progress tier (may grow in minor releases) ────────────────────────────


@dataclass(frozen=True)
class SourceStarted(CrawlEvent):
    source_name: str


@dataclass(frozen=True)
class PageCompleted(CrawlEvent):
    page: int


@dataclass(frozen=True)
class ListFetchFailed(CrawlEvent):
    page: int
    error: str


@dataclass(frozen=True)
class SourceFinished(CrawlEvent):
    stopped_by: str
    source_down: bool
    last_error: str
