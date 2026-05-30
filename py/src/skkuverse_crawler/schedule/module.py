from __future__ import annotations

from dataclasses import asdict
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection

from ..modules.base import ModuleConfig
from ..shared.db import get_db
from ..shared.fetcher import Fetcher
from ..shared.logger import get_logger
from . import fetcher_parser as fp
from .repository import upsert_year

logger = get_logger("schedule")

COLLECTION_NAME = "schedule"


async def crawl_schedule(year: int | None = None) -> dict:
    """Crawl the SKKU academic calendar.

    Discovers published years from the base page, then crawls the current year
    and any future years (user scope: current + future only). Pass ``year`` to
    target a single published academic year.
    """
    db = await get_db()
    collection = db[COLLECTION_NAME]
    fetcher = Fetcher(delay_ms=500)
    counts = {
        "years_checked": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    }
    try:
        base_html = await fetcher.fetch(fp.BASE_URL)
        available = fp.parse_available_years(base_html)
        current = fp.parse_served_year(base_html)
        if not available or current is None:
            logger.warning(
                "no_years_discovered", available=available, current=current
            )
            return counts

        if year is not None:
            if year not in available:
                logger.warning(
                    "requested_year_not_published", year=year, available=available
                )
                return counts
            targets = [year]
        else:
            targets = [y for y in available if y >= current]

        logger.info(
            "schedule_crawl_targets",
            targets=targets,
            current=current,
            available=available,
        )

        for y in targets:
            counts["years_checked"] += 1
            try:
                status = await _crawl_year(collection, fetcher, y)
                counts[status] += 1
            except Exception as exc:
                counts["errors"] += 1
                logger.error("year_crawl_failed", year=y, error=str(exc))

        logger.info("schedule_crawl_done", **counts)
        return counts
    finally:
        await fetcher.close()


async def _crawl_year(
    collection: AsyncIOMotorCollection,
    fetcher: Fetcher,
    year: int,
) -> str:
    html = await fetcher.fetch(fp.year_url(year))

    served = fp.parse_served_year(html)
    if served != year:
        # Site served a different year (silent fallback for an unpublished
        # year). Never store current data under the requested year's _id.
        logger.warning("silent_year_fallback", requested=year, served=served)
        return "skipped"

    events = fp.parse_events(html)
    if not events:
        # Don't overwrite a populated year with an empty parse (defensive).
        logger.warning("no_events_parsed", year=year)
        return "skipped"

    year_doc = {
        "_id": year,
        "academicYear": year,
        "events": [asdict(e) for e in events],
        "eventCount": len(events),
        "yearHash": fp.compute_year_hash(events),
        "sourceUrl": fp.year_url(year),
    }
    status = await upsert_year(collection, year_doc)
    logger.info("year_crawled", year=year, events=len(events), status=status)
    return status


class ScheduleModule:
    @property
    def config(self) -> ModuleConfig:
        return ModuleConfig(
            name="schedule",
            collection_name=COLLECTION_NAME,
            cron_schedule="30 5 * * *",
            run_on_start=True,
        )

    async def run(self, incremental: bool = True, **kwargs: Any) -> dict:
        return await crawl_schedule()

    async def shutdown(self) -> None:
        pass
