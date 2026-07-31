"""L2 daily crawl-health summary module (09:00 KST — container TZ is KST)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId

from ..core.module import ModuleConfig
from ..modules.notices.config.loader import load_and_validate
from ..shared.db import get_db
from ..shared.discord import send_discord
from ..shared.logger import get_logger
from .logic import format_daily_summary
from .store import COLLECTION

logger = get_logger("crawl_health_summary")


async def run_daily_summary() -> dict:
    now = datetime.now(timezone.utc)
    db = await get_db()

    departments = load_and_validate()
    enabled_ids = {
        d["id"] for d in departments if d.get("crawlAvailable") and d.get("crawlEnabled")
    }
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

    # New docs in the last 24h via the ObjectId embedded timestamp — no schema
    # change needed, and unlike crawledAt it is not refreshed by touch updates.
    cutoff = ObjectId.from_datetime(now - timedelta(hours=24))
    inserted_24h = await db["notices"].count_documents({"_id": {"$gte": cutoff}})

    message = format_daily_summary(
        now=now,
        enabled_count=enabled_count,
        failing=failing,
        inserted_24h=inserted_24h,
    )
    sent = await send_discord(message)
    logger.info(
        "daily_summary_done",
        enabled=enabled_count,
        failing=len(failing),
        inserted_24h=inserted_24h,
        sent=sent,
    )
    return {
        "enabled": enabled_count,
        "failing": len(failing),
        "inserted24h": inserted_24h,
        "sent": sent,
    }


class CrawlHealthSummaryModule:
    @property
    def config(self) -> ModuleConfig:
        return ModuleConfig(
            name="crawl-health-summary",
            cron_schedule="0 9 * * *",
        )

    async def run(self, incremental: bool = True, **kwargs: Any) -> dict:
        return await run_daily_summary()

    async def shutdown(self) -> None:
        pass
