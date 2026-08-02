"""The public crawl API — everything a third party needs to consume or
extend a crawl, and nothing that ties it to this deployment.

Re-exports are eager because every module under ``core/`` is stdlib-only
by contract. That is not just cheap, it is load-bearing: it turns
``import skkuverse_crawler.core`` into a one-line proof that the whole
core is infra-free (tests/structure test_core_import_is_infra_free), which
previously took an explicit list of every submodule.

Three things are deliberately NOT here:

- ``core.settings`` (``Config``, ``CrawlerEnv``) — deployment configuration
  is not part of the crawl contract. Exporting it would freeze the shape
  of this service's settings under the 0.x promise below, for no third
  party's benefit; ``from skkuverse_crawler.core.settings import Config``
  still works for the callers inside this repo that need it.
- ``core.registry`` — a process-global mutable dict. A public API should
  not hand out ambient state.
- ``core.testing`` — reachable as a submodule
  (``from skkuverse_crawler.core.testing import assert_sink_contract``).
  Keeping a test helper out of the runtime namespace is the same
  convention as ``unittest.mock``.

**Stability (0.x).** The RESULT tier of the event vocabulary — the events
that carry a write — is frozen: adding to it or changing one of its fields
is a major-version event. The PROGRESS tier may grow in minor releases,
which is safe precisely because sinks are tolerant readers and return
``None`` for anything they do not recognise. Until 1.0 both promises are
provisional; 1.0 itself waits on a second module proving the abstraction
(adr-006 §⑬). See docs/sink-authors-guide.md.
"""

from __future__ import annotations

from .crawl import CrawlMode, FullSweep, Incremental
from .events import (
    ChangeInfo,
    ContentRefreshed,
    CrawlEvent,
    ItemFailed,
    ItemSkipped,
    ListFetchFailed,
    NoticeCrawled,
    NoticeUnchanged,
    PageCompleted,
    SourceFinished,
    SourceStarted,
)
from .module import CrawlModule, ModuleConfig
from .pipeline import ContentDoc, Pipeline, Stage, StageContext
from .ports import (
    DetailRef,
    Notifier,
    NullSink,
    NullWorkSeed,
    Outcome,
    Ports,
    SeenIndex,
    SeenRecord,
    Sink,
    SourceSpec,
    WorkSeed,
)
from .results import SourceResult
from .runner import run_events
from .sinks import JsonLinesSink
from .sources import SourceConfigError

__all__ = [
    # ── events: the base, and the change payload a tier-1 edit carries ──
    "CrawlEvent",
    "ChangeInfo",
    # ── events, result tier: frozen until 1.0 (adding one = major) ──
    "ContentRefreshed",
    "ItemFailed",
    "ItemSkipped",
    "NoticeCrawled",
    "NoticeUnchanged",
    # ── events, progress tier: may grow in a minor release ──
    "ListFetchFailed",
    "PageCompleted",
    "SourceFinished",
    "SourceStarted",
    # ── ports: implement these to plug in storage or notification ──
    "Notifier",
    "SeenIndex",
    "Sink",
    "WorkSeed",
    # ── port values ──
    "DetailRef",
    "Outcome",
    "SeenRecord",
    "SourceSpec",
    # ── null objects + the bundle handed to a crawl ──
    "NullSink",
    "NullWorkSeed",
    "Ports",
    # ── crawl mode: a sum type, so "incremental with no index" cannot be
    #    written down at all ──
    "CrawlMode",
    "FullSweep",
    "Incremental",
    # ── driving a crawl and reading its outcome ──
    "SourceResult",
    "run_events",
    # ── core's only concrete sink: one JSON object per notice ──
    "JsonLinesSink",
    # ── content pipeline vocabulary (shapes only; stages live with the
    #    module that owns the content semantics) ──
    "ContentDoc",
    "Pipeline",
    "Stage",
    "StageContext",
    # ── module protocol, for a second module on this framework ──
    "CrawlModule",
    "ModuleConfig",
    # ── the one error a library caller must catch ──
    "SourceConfigError",
]
