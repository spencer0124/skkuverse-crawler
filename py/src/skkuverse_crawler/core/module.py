from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class ModuleConfig:
    name: str
    cron_schedule: str | None = None
    interval_seconds: int | None = None
    run_on_start: bool = False
    # How late a tick may start before it is dropped instead of run. None
    # means "whatever the scheduler plugin considers normal" — core does
    # not pick a number, because the right one depends on the cadence, not
    # on the module.
    #
    # It has to be per-module: the tolerance that suits a 30-minute cron
    # silently swallows most of a 10-second poller's ticks, and misfire is
    # evaluated BEFORE coalesce, so a late tick is dropped whole rather
    # than merged into the next one.
    misfire_grace_time: int | None = None


@runtime_checkable
class CrawlModule(Protocol):
    @property
    def config(self) -> ModuleConfig: ...

    # kwargs-only: whether a module has an incremental mode is its own
    # business, not a framework concept. NoticesModule still takes
    # `incremental: bool` and translates it to a CrawlMode; the scheduler
    # just calls run().
    async def run(self, **kwargs: Any) -> dict: ...

    async def shutdown(self) -> None: ...
