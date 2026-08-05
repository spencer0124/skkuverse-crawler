# skkuverse-crawler

Crawls notices from ~140 Sungkyunkwan University department sites, cleans the HTML, and
hands you structured records — title, date, attachments, sanitized HTML, Markdown.

Every university department runs a different CMS. Nine crawl strategies and a config file
(`sources.json`) absorb that; the code above them does not know which one it is talking to.

The crawl core needs no database, no environment variables, and no configuration. Storage,
scheduling, AI summarization and alerting are optional plugins behind extras.

## Install

```bash
pip install skkuverse-crawler                       # crawl, parse, clean, CLI
pip install 'skkuverse-crawler[mongo,sched,ai,discord]'   # + storage, scheduling, plugins
```

## Read a source's notices

<!-- example: py/examples/quickstart.py -->
```python
"""Read one source's notices. No database, no configuration, no env vars.

Run it: python examples/quickstart.py
"""

import asyncio
import logging

import structlog

from skkuverse_crawler import iter_notices

# The crawler logs through structlog, and so do the strategies it loads.
# Where that goes is the application's call, not the library's — silence
# it here so the output below is only notices.
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL))


async def main() -> None:
    async for notice in iter_notices("skku-main"):
        print(f"{notice.date}  {notice.title}")


asyncio.run(main())
```

`iter_notices` is a full sweep — with no store to compare against, every item is new — so it
reads one page by default and stops at the service start date. Pass `max_pages=` to go
deeper. Source ids come from [`sources.json`](sources.json); pass a dict of your own instead
if you are not using the bundled config.

## Send them somewhere: write a sink

Under the facade the crawl is an event stream. A sink consumes it, and the runner tallies
the outcome your `accept` reports.

<!-- example: py/examples/custom_sink.py -->
```python
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
    ItemCrawled,
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

    Note what is stored: the two fields, not the event. An ItemCrawled
    holds a notice that can carry megabytes of cleanHtml, so a sink that
    appends events to a list keeps all of that alive for the whole crawl.
    """

    def __init__(self) -> None:
        self.titles: dict[int, str] = {}

    async def prepare(self, source: SourceSpec) -> None:
        """Per-source setup. Called once before any event for that source."""

    async def accept(self, event: CrawlEvent) -> Outcome | None:
        match event:
            case ItemCrawled(item=notice):
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
        print(f"{result.source_id}: {result.inserted} inserted, {result.errors} errors")
    for article_no, title in list(sink.titles.items())[:5]:
        print(f"  {article_no}  {title}")


asyncio.run(main())
```

Both files above are the real ones in [`py/examples/`](py/examples/), byte for byte — a test
asserts it and CI runs them against a core-only install, so an example that stops working
fails the build rather than the reader.

Writing a sink for real: **[docs/sink-authors-guide.md](docs/sink-authors-guide.md)**.

## Events

The crawl emits two tiers, and the difference is a versioning promise rather than a taxonomy.

| Tier | Events | Promise |
|------|--------|---------|
| **Result** — something was crawled | `ItemCrawled` `ItemUnchanged` `ContentRefreshed` `ItemFailed` `ItemSkipped` | Frozen. Adding or changing one is a major release. |
| **Progress** — where the crawl is | `SourceStarted` `BatchCompleted` `ListFetchFailed` `SourceFinished` | May grow in a minor release. |

Growing the progress tier is safe only because sinks are tolerant readers: an event you do
not recognise must return `None`, never raise. `assert_sink_contract` checks that for you.

## Versioning

**0.x.** The tiers above describe the intent; below 1.0 both are provisional, and the 0.x
window is the last chance to correct the vocabulary before anyone depends on it.

1.0 is gated on a second module actually running on this framework — an abstraction with one
consumer is a guess, not a design ([adr-006 §⑬](docs/decisions/adr-006-core-plugin-split.md)).

## Command line

```bash
skkuverse-crawler notices --source skku-main --pages 1 --json   # crawl to stdout, no store
skkuverse-crawler notices --once                                # crawl and store
skkuverse-crawler start                                         # run the scheduler
```

`--json` is the whole core-only install in one command: JSON Lines on stdout, logs on stderr,
no database. Everything else needs an extra, and says which one if it is missing.

## Architecture

`core/` is the crawl vocabulary — ports, events, the runner, the pipeline shapes — and imports
no infrastructure. `modules/notices/` owns what a notice is and how to crawl one. `plugins/`
adapts to the outside world: MongoDB, Discord, the AI summarizer, APScheduler. `wiring.py` is
the only place plugins are assembled, so the crawl logic never reaches for its dependencies.

The boundaries are enforced by tests, not convention: `modules/` importing `plugins/` fails an
AST scan, and `import skkuverse_crawler.core` fails if it pulls in a driver.

- [Architecture](docs/architecture.md) · [Core/plugin design](docs/core-plugin-architecture.md) · [Decisions](docs/decisions/)
- [Notice schema](docs/notice-schema.md) · [Crawl flow](docs/crawl-flow-guide.md) · [Strategies](docs/strategies/)

## Development

```bash
cd py
uv sync --extra dev
uv run pytest tests/ -q          # unit + golden + structure
uv run pytest -m mongo -q        # conformance, needs Docker or MONGO_TEST_URL
uv run ruff check src/ && uv run mypy src/
```

Adding or changing a department is a `sources.json` edit plus
`python scripts/generate_artifacts.py`, which regenerates every derived artifact from it.
