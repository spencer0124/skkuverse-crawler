"""Crawl event vocabulary — two tiers (adr-006 결정 ⑧).

Result tier is the stable API: adding or changing one is a MAJOR version
event once published. Progress tier may grow in minor releases. Sinks are
tolerant readers: unknown events are silently ignored (``case _: return
None``) — pinned by the sink contract test.

Events are frozen but may hold mutable payloads (an item carries lists,
ItemUnchanged carries a mapping), so they are not hashable in practice;
nothing hashes events.

The vocabulary is domain-neutral by contract: nothing here may name a
concept belonging to one module. Core carried ``NoticeCrawled`` /
``NoticeUnchanged`` and a TYPE_CHECKING import of the notices ``Notice``
while notices was the only module — a core → modules edge the layering
rule forbids, kept on the excuse that there was only one module to leak.
Preparing for a second one retired it (adr-006, 2026-08-04 amendment).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .ports import DetailRef, SeenRecord


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
class ItemCrawled(CrawlEvent):
    """A fetched item ready to store. change=None means a new item
    (plain upsert); a populated change means a tier-1 detected edit
    (history-preserving update).

    ``item`` is deliberately untyped. Core used to annotate it as the
    notices ``Notice`` behind a TYPE_CHECKING import — a reverse-layer
    edge (core → modules) that the module boundary is supposed to forbid.
    Nothing in core ever reached *into* the value: the one core consumer,
    JsonLinesSink, calls ``dataclasses.asdict`` on it. So the annotation
    bought no checking and cost the layering rule.

    A ``CrawlItem`` Protocol was considered and rejected. Storage policy —
    which fields are insert-only, which get history-pushed — is the sink's
    business and cannot be expressed as "serialise yourself"; a protocol
    designed against one implementor would just be Notice's interface with
    the names filed off. Sinks narrow the type themselves (see
    plugins/mongo/sink.py, which keeps its own sanctioned plugins → modules
    import).
    """

    item: Any
    previous: SeenRecord | None = None
    change: ChangeInfo | None = None


@dataclass(frozen=True)
class ItemUnchanged(CrawlEvent):
    """A known, unmodified item — the sink batches these and emits one
    bulk touch per flush (crawledAt refresh; plan 위험 ②).

    ``fields`` carries whatever the module wants refreshed on an otherwise
    untouched document. Notices puts ``{"views": n}`` there; it used to be
    a ``views: int`` field on this class, which made a notices-specific
    column part of the core vocabulary. Modules with no such counter pass
    an empty mapping and still get the crawledAt touch.
    """

    article_no: int
    fields: Mapping[str, Any] = field(default_factory=dict)


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
class BatchCompleted(CrawlEvent):
    """A unit of work finished and the sink may flush.

    Named for the runner's use of it rather than for pagination: the
    aggregation table's only reaction is ``await sink.flush()``. A module
    that does not paginate emits it whenever a batch of writes is safe to
    durably commit — or never, since run_crawl flushes once more after the
    stream ends.
    """

    index: int


@dataclass(frozen=True)
class ListFetchFailed(CrawlEvent):
    page: int
    error: str


@dataclass(frozen=True)
class SourceFinished(CrawlEvent):
    stopped_by: str
    source_down: bool
    last_error: str
