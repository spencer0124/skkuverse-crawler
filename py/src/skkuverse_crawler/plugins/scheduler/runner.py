"""APScheduler-backed module runner.

A plugin because the schedule is a deployment concern, not a crawl one:
the same modules run fine from the CLI, from a test, or from someone
else's scheduler. What lives here is only the apscheduler mechanics —
assembly happens in wiring, before this is called.
"""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable, Sequence

from ...core.module import CrawlModule
from ...shared.logger import get_logger

logger = get_logger("scheduler")

SHUTDOWN_TIMEOUT_SECONDS = 5.0


def build_trigger(module: CrawlModule):
    """Cron wins over interval; a module with neither is not scheduled."""
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    config = module.config
    if config.cron_schedule:
        return CronTrigger.from_crontab(config.cron_schedule)
    if config.interval_seconds:
        return IntervalTrigger(seconds=config.interval_seconds)
    return None


async def run_scheduler(
    modules: Sequence[CrawlModule],
    *,
    module_filter: str | None = None,
    on_shutdown: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Schedule every module, run the run_on_start ones, wait for a signal."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    selected = [
        m for m in modules if not module_filter or m.config.name == module_filter
    ]

    scheduler = AsyncIOScheduler()
    for module in selected:
        trigger = build_trigger(module)
        if trigger is None:
            continue
        scheduler.add_job(
            module.run, trigger,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=10,
        )

    scheduler.start()

    for module in selected:
        if module.config.run_on_start:
            await module.run()

    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)
    await stop_event.wait()

    scheduler.shutdown(wait=False)
    try:
        # Every module, not just the scheduled ones — matches the previous
        # registry.all_modules() shutdown and keeps this a pure move.
        await asyncio.wait_for(
            _shutdown_modules(modules), timeout=SHUTDOWN_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        logger.warning("force_exit_after_timeout")
    finally:
        if on_shutdown is not None:
            await on_shutdown()


async def _shutdown_modules(modules: Sequence[CrawlModule]) -> None:
    for module in modules:
        await module.shutdown()
