"""The plugin-less sweep gate (plan PR 5 검증 게이트).

run_crawl with injected Null/Recording ports must complete a real
fixture-served crawl without ever touching get_db or importing wiring's
Mongo plugins — the "core requires nothing" acceptance case in its PR 5
form (PR 6 re-aims it at FullSweep()+NullSink).
"""

from __future__ import annotations

from unittest.mock import patch

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


async def test_sweep_with_injected_ports_never_touches_db():
    sink = RecordingSink()
    ports = Ports(sink=sink)

    async def noop_rate_limit(self: Fetcher) -> None:
        return None

    async def forbidden_get_db():
        raise AssertionError("get_db must not be called when ports are injected")

    with (
        patch(
            "skkuverse_crawler.modules.notices.orchestrator.get_db",
            side_effect=forbidden_get_db,
        ),
        patch.object(Fetcher, "_rate_limit", noop_rate_limit),
        respx.mock(assert_all_called=False) as respx_router,
    ):
        respx_router.route().mock(side_effect=_router().handler)
        results = await run_crawl(
            [depts.SKKU_STD_DEPT],
            CrawlOptions(max_pages=1),
            ports=ports,
            mode=FullSweep(),
        )

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
    assert sink.flushes == 1  # PageCompleted → flush, once for the one page

    # prepare received this source's spec; the sink satisfies the protocol.
    assert sink.prepared == [SourceSpec(source_id="golden-std", name="골든 표준 게시판")]
    assert isinstance(sink, Sink)
