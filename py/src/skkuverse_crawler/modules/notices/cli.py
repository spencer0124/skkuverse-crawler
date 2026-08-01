from __future__ import annotations

import asyncio

import click

from ...core.crawl import FullSweep, Incremental
from ...shared.db import close_client
from ...shared.logger import configure_logging
from .config.loader import load_and_validate
from .orchestrator import CrawlOptions, run_crawl

@click.command("notices")
@click.option("--once", is_flag=True, help="Run once and exit")
@click.option("--all", "full_crawl", is_flag=True, help="Full (non-incremental) crawl")
@click.option("--source", "dept", multiple=True, help="Department ID(s) to crawl")
@click.option("--pages", type=int, default=None, help="Max pages per department")
@click.option("--delay", type=int, default=500, help="Delay between requests (ms)")
def notices_cli(once: bool, full_crawl: bool, dept: tuple[str, ...], pages: int | None, delay: int) -> None:
    """Run the notices crawler."""
    from ...shared.config import init_config

    cfg = init_config()
    configure_logging(cfg)
    asyncio.run(_run(once, full_crawl, dept, pages, delay))


async def _run(
    once: bool,
    full_crawl: bool,
    dept_filter: tuple[str, ...],
    max_pages: int | None,
    delay_ms: int,
) -> None:
    departments = load_and_validate()

    options = CrawlOptions(
        max_pages=max_pages,
        delay_ms=delay_ms,
        dept_filter=dept_filter if dept_filter else None,
    )

    # Assembly at the entry point, not in the crawl logic: this is a CLI
    # leaf, so reaching for wiring here is the sanctioned direction (the
    # orchestrator no longer does). Lazy so `--help` stays import-light.
    from ...wiring import notices_ports

    ports, seen = await notices_ports()

    try:
        await run_crawl(
            departments,
            options,
            ports=ports,
            mode=FullSweep() if full_crawl else Incremental(seen),
        )
    finally:
        await close_client()
