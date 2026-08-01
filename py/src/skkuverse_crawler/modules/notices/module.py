from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ...core.crawl import FullSweep, Incremental
from ...core.module import ModuleConfig
from ...core.ports import Ports, SeenIndex
from ...core.results import SourceResult
from ...shared.config import get_config
from .config.loader import load_and_validate
from .orchestrator import CrawlOptions, run_crawl
from .update_checker import run_update_check

PortsFactory = Callable[[], Awaitable[tuple[Ports, SeenIndex]]]
ResultsHook = Callable[[list[SourceResult]], Awaitable[None]]


class NoticesModule:
    """The scheduled crawl. Everything infra-shaped is injected by wiring.

    ``ports_factory`` is awaited once per run, never cached: the Mongo
    sink's prepare guard and touch buffer are instance state, so a reused
    bundle would skip ensure_indexes on run 2 and could leak a failed
    flush's touches into run 3.

    ``on_results`` is the post-crawl hook (health recording). Installed by
    wiring on the scheduler path only — ``--once`` CLI runs stay free of
    health side effects, which is what makes manual runs safe to repeat.
    """

    def __init__(
        self,
        *,
        ports_factory: PortsFactory | None = None,
        on_results: ResultsHook | None = None,
    ) -> None:
        self._ports_factory = ports_factory
        self._on_results = on_results

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
        ports: Ports | None = None
        seen: SeenIndex | None = None
        if self._ports_factory is not None:
            ports, seen = await self._ports_factory()
        # bool → CrawlMode translation at the module boundary. Incremental
        # needs a seen index; without a factory there is nothing to consult.
        mode = Incremental(seen) if incremental and seen is not None else FullSweep()
        results = await run_crawl(departments, options, ports=ports, mode=mode)
        if self._on_results is not None:
            await self._on_results(results)
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
