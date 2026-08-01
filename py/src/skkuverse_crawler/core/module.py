from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class ModuleConfig:
    name: str
    cron_schedule: str | None = None
    interval_seconds: int | None = None
    run_on_start: bool = False


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
