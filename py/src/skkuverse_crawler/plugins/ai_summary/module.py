from __future__ import annotations

from typing import Any

from ...core.module import ModuleConfig
from .processor import run_summary_batch


class NoticesSummaryModule:
    @property
    def config(self) -> ModuleConfig:
        return ModuleConfig(
            name="notices-summary",
            cron_schedule="20 * * * *",
            run_on_start=True,
        )

    async def run(self, **kwargs: Any) -> dict:
        return await run_summary_batch()

    async def shutdown(self) -> None:
        pass
