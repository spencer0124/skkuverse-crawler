from __future__ import annotations

from typing import Any

from ...core.crawl import FullSweep
from ...core.module import ModuleConfig
from ...crawl_health.store import record_and_alert
from ...shared.config import get_config
from .config.loader import load_and_validate
from .orchestrator import CrawlOptions, run_crawl
from .update_checker import run_update_check


class NoticesModule:
    @property
    def config(self) -> ModuleConfig:
        return ModuleConfig(
            name="notices",
            cron_schedule="*/30 * * * *",
        )

    async def run(self, incremental: bool = True, **kwargs: Any) -> dict:
        departments = load_and_validate()
        options = CrawlOptions(
            dept_filter=get_config().dept_filter,
        )
        # bool → CrawlMode translation at the module boundary: None lets
        # run_crawl resolve Incremental over the lazily-wired Mongo index.
        results = await run_crawl(
            departments, options, mode=None if incremental else FullSweep()
        )
        await record_and_alert(results)
        return {
            "departments": len(results),
            "inserted": sum(r.inserted for r in results),
            "updated": sum(r.updated for r in results),
            "skipped": sum(r.skipped for r in results),
            "errors": sum(r.errors for r in results),
        }

    async def shutdown(self) -> None:
        pass


class NoticesUpdateCheckModule:
    @property
    def config(self) -> ModuleConfig:
        return ModuleConfig(
            name="notices-update-check",
            cron_schedule="10 8,14,20 * * *",
        )

    async def run(self, incremental: bool = True, **kwargs: Any) -> dict:
        departments = load_and_validate()
        results = await run_update_check(
            departments,
            dept_filter=get_config().dept_filter,
        )
        return {
            "departments": len(results),
            "checked": sum(r.total_checked for r in results),
            "changed": sum(r.content_changed for r in results),
            "backfilled": sum(r.hash_backfilled for r in results),
            "errors": sum(r.fetch_errors for r in results),
        }

    async def shutdown(self) -> None:
        pass
