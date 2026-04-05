from __future__ import annotations

from typing import Any

from ..modules.base import ModuleConfig
from .fetcher import update_jongro_buses


class BusJongroModule:
    @property
    def config(self) -> ModuleConfig:
        return ModuleConfig(
            name="bus-jongro",
            collection_name="bus_cache",
            interval_seconds=40,
        )

    async def run(self, incremental: bool = True, **kwargs: Any) -> dict:
        return await update_jongro_buses()

    async def shutdown(self) -> None:
        pass
