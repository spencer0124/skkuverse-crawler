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
    from .shared.config import init_config

    init_config()
    configure_logging()
    asyncio.run(_start_scheduler(module))


async def _start_scheduler(module_filter: str | None = None) -> None:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    from .modules import registry
    from .shared.db import close_client

    # Register modules
    from .notices.module import NoticesModule, NoticesUpdateCheckModule

    registry.register(NoticesModule())
    registry.register(NoticesUpdateCheckModule())

    scheduler = AsyncIOScheduler()

    for mod in registry.all_modules():
        if module_filter and mod.config.name != module_filter:
            continue
        if mod.config.cron_schedule:
            trigger = CronTrigger.from_crontab(mod.config.cron_schedule)
        elif mod.config.interval_seconds:
            trigger = IntervalTrigger(seconds=mod.config.interval_seconds)
        else:
            continue
        scheduler.add_job(
            mod.run, trigger,
            kwargs={"incremental": True},
            max_instances=1,
            coalesce=True,
            misfire_grace_time=10,
        )

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

    # Graceful shutdown with 5s timeout
    from .shared.logger import get_logger
    logger = get_logger("shutdown")

    scheduler.shutdown(wait=False)
    try:
        await asyncio.wait_for(
            _shutdown_modules(registry.all_modules()),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        logger.warning("force_exit_after_timeout")
    finally:
        await close_client()


async def _shutdown_modules(modules: list) -> None:
    for mod in modules:
        await mod.shutdown()


# Register notices CLI subcommands
from .notices.cli import notices_cli, update_check_cli  # noqa: E402
main.add_command(notices_cli)
main.add_command(update_check_cli)
