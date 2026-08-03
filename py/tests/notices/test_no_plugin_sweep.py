"""The plugin-less sweep gate (plan PR 5 검증 게이트).

run_crawl with injected Null/Recording ports must complete a real
fixture-served crawl without ever touching a database — the "core
requires nothing" acceptance case in its PR 5 form (PR 6 re-aimed it at
FullSweep()+NullSink; PR 7 at the inverted injection).

The forbidden-get_db patch is gone because the seam it guarded is gone:
the orchestrator no longer imports get_db at all, which the structural
assertion below pins directly. The autouse _no_real_mongo fixture is the
backstop — any real Motor client construction is an AssertionError.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import respx

from skkuverse_crawler.core.crawl import FullSweep
from skkuverse_crawler.core.events import (
    NoticeCrawled,
    PageCompleted,
    SourceFinished,
    SourceStarted,
)
from skkuverse_crawler.core.ports import Ports, Sink, SourceSpec
from skkuverse_crawler.modules.notices.orchestrator import CrawlOptions, run_crawl
from skkuverse_crawler.shared.fetcher import Fetcher
from tests.characterization import depts
from tests.characterization.harness import FixtureRouter
from tests.support.ports import RecordingSink


def _router() -> FixtureRouter:
    router = (
        FixtureRouter()
        .serve(depts.std_list_url(0), "skku_standard/list_p0.html")
    )
    for article_no in (100, 101, 102, 103, 104, 105):
        router.serve(
            depts.std_detail_url(article_no), f"skku_standard/detail_{article_no}.html"
        )
    return router


async def _run_sweep(sink: RecordingSink, **run_kwargs):
    async def noop_rate_limit(self: Fetcher) -> None:
        return None

    with (
        patch.object(Fetcher, "_rate_limit", noop_rate_limit),
        respx.mock(assert_all_called=False) as respx_router,
    ):
        respx_router.route().mock(side_effect=_router().handler)
        return await run_crawl(
            [depts.SKKU_STD_DEPT],
            CrawlOptions(max_pages=1),
            ports=Ports(sink=sink),
            **run_kwargs,
        )


def test_orchestrator_has_no_database_seam():
    """The inversion, stated structurally: the crawl logic cannot reach a
    database at all.

    An attribute check alone would miss the ways the seam could come back
    without the name reappearing at module scope — an aliased import, or
    a function-body `from ...shared.db import get_db` (the lazy pattern
    wiring and plugins/mongo/audit legitimately use elsewhere). So this
    scans the source for any reference to the db module or its accessor.
    """
    import ast
    import inspect

    from skkuverse_crawler.modules.notices import orchestrator

    assert not hasattr(orchestrator, "get_db")

    tree = ast.parse(inspect.getsource(orchestrator))
    reached = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and "db" in (node.module or "").split("."):
            reached.append(f"from {node.module}")
        elif isinstance(node, ast.Import):
            reached += [a.name for a in node.names if "db" in a.name.split(".")]
        elif isinstance(node, ast.Name) and node.id == "get_db":
            reached.append("get_db reference")
    assert not reached, f"orchestrator reaches for a database: {reached}"


async def test_sweep_with_injected_ports_never_touches_db():
    sink = RecordingSink()
    results = await _run_sweep(sink, mode=FullSweep())

    assert len(results) == 1
    result = results[0]
    assert result.errors == 0
    assert result.source_down is False

    # Uniform emission: the sink sees the full stream, bookended by the
    # progress tier; every result-tier event is a fresh NoticeCrawled and
    # None outcomes all count as INSERTED.
    assert isinstance(sink.events[0], SourceStarted)
    finished = sink.events[-1]
    assert isinstance(finished, SourceFinished)
    assert finished.stopped_by == "max_pages"
    assert finished.source_down is False
    assert any(isinstance(e, PageCompleted) for e in sink.events)

    crawled = [e for e in sink.events if isinstance(e, NoticeCrawled)]
    assert crawled
    assert all(e.change is None for e in crawled)
    assert result.inserted == len(crawled)
    # Two: one on the page's PageCompleted, one when the source's stream
    # ends. The second exists because not every source reaches a
    # PageCompleted — see test_a_source_is_flushed_when_its_stream_ends.
    assert sink.flushes == 2

    # prepare received this source's spec; the sink satisfies the protocol.
    assert sink.prepared == [SourceSpec(source_id="golden-std", name="골든 표준 게시판")]
    assert isinstance(sink, Sink)


async def test_injected_ports_without_mode_defaults_to_full_sweep():
    """The honest OSS default (architecture §CrawlMode): no wired seen
    index + no explicit mode ⇒ FullSweep — pinned so the fallback branch
    in run_crawl's mode resolution has direct coverage."""
    sink = RecordingSink()
    results = await _run_sweep(sink)  # mode omitted on purpose

    assert results[0].errors == 0
    crawled = [e for e in sink.events if isinstance(e, NoticeCrawled)]
    assert crawled and all(e.change is None for e in crawled)
    finished = sink.events[-1]
    assert isinstance(finished, SourceFinished)
    assert finished.stopped_by == "max_pages"


async def test_core_only_crawl_writes_json_lines_to_stdout():
    """The acceptance case for `pip install skkuverse-crawler`, run against
    the same fixtures as the sweep above: a real crawl, a core-only sink,
    and output a consumer can actually parse."""
    import io
    import json

    from skkuverse_crawler.core.sinks import JsonLinesSink

    stream = io.StringIO()
    results = await _run_sweep(JsonLinesSink(stream), mode=FullSweep())

    assert results[0].errors == 0
    lines = stream.getvalue().splitlines()
    assert lines, "a core-only crawl that prints nothing is not a crawl"
    assert len(lines) == results[0].inserted

    payloads = [json.loads(line) for line in lines]
    assert all(p["sourceId"] == "golden-std" for p in payloads)
    assert all(p["title"] for p in payloads)
    # Progress events must not have leaked into the stream.
    assert all("articleNo" in p for p in payloads)


async def test_a_source_is_flushed_when_its_stream_ends():
    """A batching sink must not be left holding writes.

    run_events flushes on PageCompleted, and not every source reaches one:
    the null-content backfill emits write-bearing events before the page
    loop, and a page-0 failure breaks out before the first page completes.
    Those writes used to sit in the buffer while the runner counted them as
    stored — so the end-of-source flush is the fix, and this pins it.
    """

    class _TimelineSink(RecordingSink):
        """Records how many events had arrived at each flush, which is what
        distinguishes the end-of-source flush from the per-page one."""

        def __init__(self) -> None:
            super().__init__()
            self.event_counts_at_flush: list[int] = []

        async def flush(self) -> None:
            self.event_counts_at_flush.append(len(self.events))
            await super().flush()

    sink = _TimelineSink()
    await _run_sweep(sink, mode=FullSweep())

    pages = sum(1 for e in sink.events if isinstance(e, PageCompleted))
    assert sink.flushes == pages + 1, (
        f"expected one flush per page ({pages}) plus one at the end, got {sink.flushes}"
    )
    # The last flush saw every event, including SourceFinished — i.e. it ran
    # after the stream was exhausted, not during it.
    assert sink.event_counts_at_flush[-1] == len(sink.events)
    assert isinstance(sink.events[-1], SourceFinished)


async def test_a_source_that_never_completes_a_page_is_still_flushed():
    """The case the end-of-source flush was actually written for.

    A page-0 fetch failure breaks out of the loop before any
    PageCompleted, so the per-page flush never runs. Before the fix a
    batching sink kept whatever it had buffered — and the runner had
    already counted it. The healthy-path test above cannot see this,
    because there the per-page flush covers it anyway.
    """

    class _CountingSink(RecordingSink):
        pass

    sink = _CountingSink()

    async def noop_rate_limit(self: Fetcher) -> None:
        return None

    with (
        patch.object(Fetcher, "_rate_limit", noop_rate_limit),
        respx.mock(assert_all_called=False) as respx_router,
    ):
        # Every request fails, so page 0's list fetch dies immediately.
        respx_router.route().mock(side_effect=httpx.ConnectError("down"))
        results = await run_crawl(
            [depts.SKKU_STD_DEPT],
            CrawlOptions(max_pages=1),
            ports=Ports(sink=sink),
            mode=FullSweep(),
        )

    assert results[0].source_down is True
    assert not any(isinstance(e, PageCompleted) for e in sink.events), (
        "this test is only meaningful if no page completes"
    )
    assert sink.flushes == 1, "a source that never completed a page was never flushed"
