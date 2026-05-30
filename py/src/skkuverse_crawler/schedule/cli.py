from __future__ import annotations

import asyncio

import click

from ..shared.db import close_client
from ..shared.logger import configure_logging


@click.command("schedule")
@click.option("--year", type=int, default=None, help="Crawl a single academic year")
@click.option("--once", is_flag=True, help="Run once and exit (default behavior)")
def schedule_cli(year: int | None, once: bool) -> None:
    """Crawl the SKKU academic calendar (학사일정)."""
    from ..shared.config import init_config

    init_config()
    configure_logging()
    asyncio.run(_run(year))


async def _run(year: int | None) -> None:
    from .module import crawl_schedule

    try:
        await crawl_schedule(year=year)
    finally:
        await close_client()
