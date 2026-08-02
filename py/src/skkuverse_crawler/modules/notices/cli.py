from __future__ import annotations

import asyncio

import click

from ...core.crawl import FullSweep, Incremental
from ...shared.logger import configure_logging
from .config.loader import load_and_validate
from .orchestrator import CrawlOptions, run_crawl
from .simple import DEFAULT_MAX_PAGES

@click.command("notices")
@click.option("--once", is_flag=True, help="Run once and exit")
@click.option("--all", "full_crawl", is_flag=True, help="Full (non-incremental) crawl")
@click.option("--source", "dept", multiple=True, help="Department ID(s) to crawl")
@click.option("--pages", type=int, default=None, help="Max pages per department")
@click.option("--delay", type=int, default=500, help="Delay between requests (ms)")
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Print each notice as JSON on stdout and store nothing "
    "(implies a full sweep — with no store there is nothing to compare "
    "against — and defaults to 1 page per source; raise it with --pages).",
)
def notices_cli(
    once: bool,
    full_crawl: bool,
    dept: tuple[str, ...],
    pages: int | None,
    delay: int,
    json_output: bool,
) -> None:
    """Run the notices crawler."""
    import sys

    from ...env import init_config

    cfg = init_config()
    # With --json, stdout is the crawl's output; diagnostics move to stderr
    # so the stream stays one-JSON-object-per-line.
    configure_logging(cfg, stream=sys.stderr if json_output else None)
    asyncio.run(_run(once, full_crawl, dept, pages, delay, json_output))


async def _run(
    once: bool,
    full_crawl: bool,
    dept_filter: tuple[str, ...],
    max_pages: int | None,
    delay_ms: int,
    json_output: bool = False,
) -> None:
    departments = load_and_validate()

    options = CrawlOptions(
        max_pages=max_pages,
        delay_ms=delay_ms,
        dept_filter=dept_filter if dept_filter else None,
    )

    if json_output:
        await _run_store_less(departments, options)
        return

    _require_store()

    # Assembly at the entry point, not in the crawl logic: this is a CLI
    # leaf, so reaching for wiring here is the sanctioned direction (the
    # orchestrator no longer does). Lazy because motor is an optional
    # dependency now — a module under modules/ must import without it.
    from ...shared.db import close_client
    from ...wiring import notices_ports

    # Inside the try: get_db() creates the Motor client, so an assembly
    # failure after that point must still reach close_client().
    try:
        ports, seen = await notices_ports()
        await run_crawl(
            departments,
            options,
            ports=ports,
            mode=FullSweep() if full_crawl else Incremental(seen),
        )
    finally:
        await close_client()


# A store-less run cannot be incremental, so `max_pages` is the only thing
# standing between a casual `--json` and a full historical sweep of every
# enabled source. The orchestrator's own default for FullSweep is 2500,
# which across 140 university servers is not something a first-run command
# should do by accident.
#
# Imported rather than redeclared: iter_notices() is the other casual
# entry point and needs the same guard, and two copies of "1" with two
# copies of this reasoning is how they end up disagreeing.
STORE_LESS_DEFAULT_PAGES = DEFAULT_MAX_PAGES


async def _run_store_less(departments: list, options: CrawlOptions) -> None:
    """The core-only path: no wiring, no shared.db, no optional dependency.

    This is what `pip install skkuverse-crawler` buys — the acceptance
    case for adr-006's "the core runs with no infrastructure". FullSweep
    is not a choice: without a store there is no seen index, so every item
    is new by definition.
    """
    import dataclasses

    from ...core.ports import Ports
    from ...core.sinks import JsonLinesSink

    if options.max_pages is None:
        options = dataclasses.replace(options, max_pages=STORE_LESS_DEFAULT_PAGES)

    sink = JsonLinesSink()
    await run_crawl(departments, options, ports=Ports(sink=sink), mode=FullSweep())
    # run_events flushes on PageCompleted, but a source that dies at page 0
    # emits backfill events before the first one. stdout flushes at exit;
    # an injected file handle would not.
    await sink.flush()


def _require_store() -> None:
    """Fail with the install hint rather than deep inside motor's absence."""
    import importlib.util

    try:
        installed = importlib.util.find_spec("motor") is not None
    except ModuleNotFoundError:
        installed = False
    if not installed:
        raise click.ClickException(
            "storing notices needs the optional `mongo` dependencies — install with:\n"
            "    pip install 'skkuverse-crawler[mongo]'\n"
            "or run with --json to print to stdout instead."
        )
