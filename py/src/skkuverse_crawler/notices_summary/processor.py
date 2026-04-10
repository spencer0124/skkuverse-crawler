from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from ..shared.config import get_config
from ..shared.db import get_db
from ..shared.logger import get_logger
from .ai_client import AiClient
from .query import ensure_summary_indexes, find_stale_summaries, find_unsummarized

logger = get_logger("notices_summary")


@dataclass
class SummaryResult:
    summarized: int = 0
    stale_updated: int = 0
    errors: int = 0
    elapsed_seconds: float = 0.0


async def run_summary_batch(
    *,
    batch_size: int = 50,
    delay_seconds: float = 1.0,
) -> dict:
    config = get_config()
    client = AiClient(config.ai_service_url)
    db = await get_db()
    collection = db["notices"]

    await ensure_summary_indexes(collection)

    result = SummaryResult()
    start = time.monotonic()

    try:
        unsummarized = await find_unsummarized(collection, batch_size)
        logger.info("found_unsummarized", count=len(unsummarized))
        for doc in unsummarized:
            ok = await _summarize_one(client, collection, doc)
            if ok:
                result.summarized += 1
            else:
                result.errors += 1
            await asyncio.sleep(delay_seconds)

        stale = await find_stale_summaries(collection, batch_size)
        logger.info("found_stale_summaries", count=len(stale))
        for doc in stale:
            ok = await _summarize_one(client, collection, doc)
            if ok:
                result.stale_updated += 1
            else:
                result.errors += 1
            await asyncio.sleep(delay_seconds)
    finally:
        await client.close()

    result.elapsed_seconds = round(time.monotonic() - start, 2)
    logger.info("summary_batch_complete", **asdict(result))
    return asdict(result)


async def _summarize_one(
    client: AiClient,
    collection: Any,
    doc: dict,
) -> bool:
    article_no = doc["articleNo"]
    dept = doc.get("sourceDeptId", "")
    try:
        resp = await client.summarize(
            title=doc["title"],
            category=doc.get("category", ""),
            clean_text=doc["contentText"],
            date=doc.get("date"),
        )
        await collection.update_one(  # type: ignore[union-attr]
            {"_id": doc["_id"]},
            {
                "$set": {
                    "summary": resp["summary"],
                    "summaryOneLiner": resp["oneLiner"],
                    "summaryType": resp["type"],
                    "summaryPeriods": resp.get("periods", []),
                    "summaryLocations": resp.get("locations", []),
                    "summaryDetails": resp.get("details"),
                    "summaryModel": resp.get("model"),
                    "summaryAt": datetime.now(UTC),
                    "summaryContentHash": doc.get("contentHash"),
                    "summaryFailures": 0,
                },
            },
        )
        logger.info("summarized", articleNo=article_no, dept=dept)
        return True
    except Exception as exc:
        logger.error(
            "summarize_failed",
            articleNo=article_no,
            dept=dept,
            error=str(exc),
        )
        await collection.update_one(  # type: ignore[union-attr]
            {"_id": doc["_id"]},
            {"$inc": {"summaryFailures": 1}},
        )
        return False
