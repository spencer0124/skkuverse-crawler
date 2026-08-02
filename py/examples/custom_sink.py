"""Send crawled notices somewhere of your own, by writing a Sink.

iter_notices hides the event stream. A sink consumes it: the crawl emits
events, the runner routes them to your accept() and tallies the result.

Run it: python examples/custom_sink.py
"""

import asyncio
import logging

import structlog

from skkuverse_crawler.core import (
    ContentRefreshed,
    CrawlEvent,
    FullSweep,
    NoticeCrawled,
    Outcome,
    Ports,
    SourceResult,
    SourceSpec,
)
from skkuverse_crawler.core.testing import assert_sink_contract
from skkuverse_crawler.modules.notices.config.loader import load_and_validate
from skkuverse_crawler.modules.notices.orchestrator import CrawlOptions, run_crawl

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL))


class TitleIndexSink:
    """Keeps titles by article number, and nothing else.

    Note what is stored: the two fields, not the event. A NoticeCrawled
    holds a Notice that can carry megabytes of cleanHtml, so a sink that
    appends events to a list keeps all of that alive for the whole crawl.
    """

    def __init__(self) -> None:
        self.titles: dict[int, str] = {}

    async def prepare(self, source: SourceSpec) -> None:
        """Per-source setup. Called once before any event for that source."""

    async def accept(self, event: CrawlEvent) -> Outcome | None:
        match event:
            case NoticeCrawled(notice=notice):
                new = notice.articleNo not in self.titles
                self.titles[notice.articleNo] = notice.title
                # The runner reads this to count inserted vs updated.
                return Outcome.INSERTED if new else Outcome.UPDATED
            case ContentRefreshed():
                return Outcome.UPDATED
            case _:
                # Every other event — the whole progress tier, plus any
                # event type a future release adds. Ignoring what you do
                # not recognise is what lets the vocabulary grow without
                # breaking you.
                return None

    async def flush(self) -> None:
        """Called at the end of every page. Batching sinks write here.

        Do not swallow errors: a failing flush must propagate so the crawl
        stops treating a source as successful.
        """


async def main() -> None:
    sink = TitleIndexSink()

    # Prove the sink satisfies what the runner assumes, before crawling.
    # Without a `sample` this stores nothing, so it is safe anywhere.
    await assert_sink_contract(sink)

    sources = [s for s in load_and_validate() if s["id"] == "skku-main"]
    results: list[SourceResult] = await run_crawl(
        sources,
        CrawlOptions(max_pages=1, dept_filter=("skku-main",)),
        ports=Ports(sink=sink),
        mode=FullSweep(),
    )

    for result in results:
        print(f"{result.dept_id}: {result.inserted} inserted, {result.errors} errors")
    for article_no, title in list(sink.titles.items())[:5]:
        print(f"  {article_no}  {title}")


asyncio.run(main())
