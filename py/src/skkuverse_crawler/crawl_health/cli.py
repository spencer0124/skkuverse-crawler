from __future__ import annotations

import asyncio

import click

from ..shared.db import close_client
from ..shared.logger import configure_logging


@click.command("health-summary")
def health_summary_cli() -> None:
    """Send the daily crawl-health summary to Discord once."""
    from ..shared.config import init_config

    init_config()
    configure_logging()
    asyncio.run(_run())


async def _run() -> None:
    from .module import run_daily_summary

    try:
        await run_daily_summary()
    finally:
        await close_client()
