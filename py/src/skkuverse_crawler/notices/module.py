from __future__ import annotations

from typing import Any

from ..modules.base import ModuleConfig
from ..shared.db import close_client
from .config.loader import load_and_validate
from .orchestrator import CrawlOptions, run_crawl


class NoticesModule:
    @property
    def config(self) -> ModuleConfig:
        return ModuleConfig(
            name="notices",
            collection_name="notices",
            cron_schedule="*/30 * * * *",
        )

    async def run(self, incremental: bool = True, **kwargs: Any) -> dict:
        departments = load_and_validate()
        options = CrawlOptions(incremental=incremental)
        results = await run_crawl(departments, options)
        return {
            "departments": len(results),
            "inserted": sum(r.inserted for r in results),
            "updated": sum(r.updated for r in results),
            "skipped": sum(r.skipped for r in results),
            "errors": sum(r.errors for r in results),
        }

    async def shutdown(self) -> None:
        pass
