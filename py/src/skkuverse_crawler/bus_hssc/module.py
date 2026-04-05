from __future__ import annotations

from typing import Any

from ..modules.base import ModuleConfig
from .fetcher import update_hssc_bus_list


class BusHsscModule:
    @property
    def config(self) -> ModuleConfig:
        return ModuleConfig(
            name="bus-hssc",
            collection_name="bus_cache",
            interval_seconds=10,
        )

    async def run(self, incremental: bool = True, **kwargs: Any) -> dict:
        return await update_hssc_bus_list()

    async def shutdown(self) -> None:
        pass
