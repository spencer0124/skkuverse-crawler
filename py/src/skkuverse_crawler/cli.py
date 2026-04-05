from __future__ import annotations

import asyncio
import signal

import click

from .shared.logger import configure_logging


@click.group()
def main() -> None:
    """skkuverse-crawler: Multi-module SKKU data crawler."""
    pass


@main.command()
@click.option("--module", "-m", default=None, help="Run specific module only")
def start(module: str | None) -> None:
    """Start the cron scheduler for all (or one) module."""
    configure_logging()
    asyncio.run(_start_scheduler(module))


async def _start_scheduler(module_filter: str | None = None) -> None:
    from dotenv import load_dotenv
    load_dotenv()

    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    from .modules import registry
    from .shared.db import close_client

    # Register notices module
    from .notices.module import NoticesModule
    registry.register(NoticesModule())

    scheduler = AsyncIOScheduler()

    for mod in registry.all_modules():
        if module_filter and mod.config.name != module_filter:
            continue
        trigger = CronTrigger.from_crontab(mod.config.cron_schedule)
        scheduler.add_job(mod.run, trigger, kwargs={"incremental": True})

    scheduler.start()

    # Run all immediately
    for mod in registry.all_modules():
        if module_filter and mod.config.name != module_filter:
            continue
        await mod.run(incremental=True)

    # Wait for signal
    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)
    await stop_event.wait()

    # Graceful shutdown
    scheduler.shutdown()
    for mod in registry.all_modules():
        await mod.shutdown()
    await close_client()


# Register notices CLI subcommand
from .notices.cli import notices_cli  # noqa: E402
main.add_command(notices_cli)
