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

# What a module gets when its ModuleConfig does not say. Historically this
# was hardcoded for every job; it lives here rather than in core because
# "how late is too late" is a scheduling policy, not part of the module
# contract. APScheduler's own default is 1 second, which is far too tight
# for a crawl that shares an event loop with page parsing.
DEFAULT_MISFIRE_GRACE_SECONDS = 10


def grace_seconds(config) -> int:
    """How late a tick may start, per module, falling back to this plugin's
    default. Separate function so a test can assert the fallback without
    standing up a scheduler.

    APScheduler accepts only None or a POSITIVE integer, and rejects the
    rest with a TypeError raised from add_job — which happens before
    scheduler.start(), so one module's bad value takes down every module
    in the process, with a message naming neither. Catching it here costs
    a branch and names the module.

    "Run only if exactly on time" is therefore not expressible; the
    nearest thing is 1. Unlimited grace (APScheduler's own None) is not
    expressible either, because None is spoken for by the fallback — pass
    a large number if a module ever genuinely wants it.
    """
    grace = config.misfire_grace_time
    if grace is None:
        return DEFAULT_MISFIRE_GRACE_SECONDS
    if not isinstance(grace, int) or isinstance(grace, bool) or grace < 1:
        raise ValueError(
            f"module {config.name!r} has misfire_grace_time={grace!r}; "
            f"it must be a positive integer of seconds, or None to use "
            f"the scheduler default ({DEFAULT_MISFIRE_GRACE_SECONDS}s)"
        )
    return grace


def _log_missed_ticks(scheduler) -> None:
    """Surface dropped ticks as a structured log.

    A missed tick is silent by default: APScheduler skips the run and moves
    on, so a module starved by a busy event loop looks identical to one
    that simply had nothing to do. That matters most for the modules with
    the tightest cadence, which are exactly the ones whose grace window is
    easiest to exceed.

    This is a listener, not new instrumentation — the executor already
    detects the condition; we only give it a name and a log line.
    """
    from apscheduler.events import EVENT_JOB_MISSED

    def on_missed(event) -> None:
        logger.warning(
            "job_tick_missed",
            module=event.job_id,
            scheduled_run_time=str(getattr(event, "scheduled_run_time", "")),
        )

    scheduler.add_listener(on_missed, EVENT_JOB_MISSED)


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
    on_shutdown: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Schedule every module handed over, run the run_on_start ones, wait
    for a signal.

    There is no filter here any more. Choosing which modules run is
    ``wiring.build_runtime(selection=...)``'s job, so that unselected
    families are never built — a second filter at this layer could only
    disagree with the first, and would happily accept a name that matched
    nothing.
    """
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    selected = list(modules)

    scheduler = AsyncIOScheduler()
    for module in selected:
        trigger = build_trigger(module)
        if trigger is None:
            continue
        config = module.config
        scheduler.add_job(
            module.run, trigger,
            # The job id is the module name so the missed-tick listener
            # below can say WHICH module lost a tick. Names are unique by
            # construction (the registry keys on them).
            id=config.name,
            name=config.name,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=grace_seconds(config),
        )

    _log_missed_ticks(scheduler)
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
