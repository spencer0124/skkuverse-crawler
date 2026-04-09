from __future__ import annotations

from typing import Any

from ..modules.base import ModuleConfig
from .processor import run_summary_batch


class NoticesSummaryModule:
    @property
    def config(self) -> ModuleConfig:
        return ModuleConfig(
            name="notices-summary",
            collection_name="notices",
            cron_schedule=None,  # disabled until AI prompt update
            run_on_start=False,
        )

    async def run(self, incremental: bool = True, **kwargs: Any) -> dict:
        return await run_summary_batch()

    async def shutdown(self) -> None:
        pass
