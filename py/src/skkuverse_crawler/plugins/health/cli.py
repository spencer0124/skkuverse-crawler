from __future__ import annotations

import asyncio

import click

from ...shared.logger import configure_logging


@click.command("health-summary")
def health_summary_cli() -> None:
    """Send the daily crawl-health summary to Discord once."""
    from ...env import init_config

    cfg = init_config()
    configure_logging(cfg)
    asyncio.run(_run())


async def _run() -> None:
    # A CLI command is an assembly leaf: picking the concrete notifier is
    # its job, the same way wiring picks one for the scheduler.
    from ...shared.db import close_client
    from ..discord.webhook import DiscordNotifier
    from .module import run_daily_summary

    try:
        await run_daily_summary(DiscordNotifier())
    finally:
        await close_client()
