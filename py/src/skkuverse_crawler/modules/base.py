from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class ModuleConfig:
    name: str
    cron_schedule: str
    collection_name: str


@runtime_checkable
class CrawlModule(Protocol):
    @property
    def config(self) -> ModuleConfig: ...

    async def run(self, incremental: bool = True, **kwargs: Any) -> dict: ...

    async def shutdown(self) -> None: ...
