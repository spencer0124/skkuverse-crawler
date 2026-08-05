"""L2 daily crawl-health summary module (09:00 KST — container TZ is KST).

Family-agnostic: it used to read the notices source list and count
``db["notices"]`` directly, which made the one module whose job is
"is the crawler healthy" answer only for one crawler. It now asks
injected probes, so a second module family reports through the same
09:00 message instead of needing its own.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ...core.module import ModuleConfig
from ...core.ports import Notifier
from ...shared.db import get_db
from ...shared.logger import get_logger
from .logic import format_daily_summary
from .store import COLLECTION

logger = get_logger("crawl_health_summary")


@dataclass(frozen=True)
class CoverageProbe:
    """What one module family contributes to the daily summary.

    Callables rather than data because the summary runs once a day and
    should read the live source list, not one captured at assembly time.

    The asymmetry is deliberate: ``enabled_ids`` is sync because a source
    list is local (a parsed config file), while ``inserted_since`` queries
    a database. A probe whose id lookup would go over a network should
    cache it rather than block the loop here.
    """

    name: str
    # Sources this family expects to be crawling right now.
    enabled_ids: Callable[[], set[str]]
    # Documents this family stored since the given instant, or None when
    # the family has no such number. The snapshot archetype is the case:
    # its `_id` is a constant string and its document is upserted forever,
    # so "created in the last 24 hours" has no answer — under a TTL a count
    # would measure liveness instead, and a hardcoded 0 would look like one.
    # Probes without it still contribute their enabled ids, which is the
    # half that decides whether a failing source appears in the summary
    # at all.
    inserted_since: Callable[[datetime], Awaitable[int]] | None = None


async def run_daily_summary(
    notifier: Notifier, probes: Sequence[CoverageProbe] = ()
) -> dict:
    now = datetime.now(timezone.utc)
    db = await get_db()

    enabled_ids: set[str] = set()
    for probe in probes:
        enabled_ids |= probe.enabled_ids()
    enabled_count = len(enabled_ids)

    # Restrict to currently-enabled sources: a source retired via
    # crawlAvailable=false leaves a stale crawl_health doc behind (it never
    # "recovers" because it is no longer crawled) and must not haunt the
    # summary forever.
    failing = [
        doc
        async for doc in db[COLLECTION].find({"consecutiveFailures": {"$gt": 0}})
        if doc.get("sourceId") in enabled_ids
    ]

    cutoff = now - timedelta(hours=24)
    inserted_24h = sum(
        [
            await probe.inserted_since(cutoff)
            for probe in probes
            if probe.inserted_since is not None
        ]
    )

    from ...env import get_config
    from ...wiring import active_plugins

    plugins = active_plugins(get_config())

    message = format_daily_summary(
        now=now,
        enabled_count=enabled_count,
        failing=failing,
        inserted_24h=inserted_24h,
        plugins=plugins,
    )
    sent = await notifier.notify(message)
    logger.info(
        "daily_summary_done",
        enabled=enabled_count,
        failing=len(failing),
        inserted_24h=inserted_24h,
        plugins=list(plugins),
        sent=sent,
    )
    return {
        "enabled": enabled_count,
        "failing": len(failing),
        "inserted24h": inserted_24h,
        "sent": sent,
    }


class CrawlHealthSummaryModule:
    """Wiring supplies the notifier and the probes — this module never
    picks a channel, and never names a module family."""

    def __init__(
        self, notifier: Notifier, probes: Sequence[CoverageProbe] = ()
    ) -> None:
        self._notifier = notifier
        self._probes = tuple(probes)

    @property
    def config(self) -> ModuleConfig:
        return ModuleConfig(
            name="crawl-health-summary",
            cron_schedule="0 9 * * *",
        )

    async def run(self, **kwargs: Any) -> dict:
        return await run_daily_summary(self._notifier, self._probes)

    async def shutdown(self) -> None:
        pass
