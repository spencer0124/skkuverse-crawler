from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class ModuleConfig:
    name: str
    collection_name: str
    cron_schedule: str | None = None
    interval_seconds: int | None = None
    run_on_start: bool = False


@runtime_checkable
class CrawlModule(Protocol):
    @property
    def config(self) -> ModuleConfig: ...

    async def run(self, incremental: bool = True, **kwargs: Any) -> dict: ...

    async def shutdown(self) -> None: ...
