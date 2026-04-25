from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from pymongo import ReturnDocument

from ..shared.db import get_db
from ..shared.fetcher import Fetcher
from ..shared.html_cleaner import clean_html, normalize_content_urls
from ..shared.logger import get_logger
from .constants import SERVICE_START_DATE
from .dedup import ensure_indexes
from .hashing import compute_content_hash
from .orchestrator import STRATEGY_MAP


@dataclass
class UpdateCheckResult:
    source_id: str = ""
    total_checked: int = 0
    content_changed: int = 0
    hash_backfilled: int = 0
    fetch_errors: int = 0
    skipped_no_detail: int = 0
    not_found: int = 0
    soft_deleted: int = 0
    elapsed_seconds: float = 0.0


async def run_update_check(
    departments: list[dict[str, Any]],
    window_days: int = 14,
    dept_filter: tuple[str, ...] | None = None,
) -> list[UpdateCheckResult]:
    logger = get_logger("update_checker")

    db = await get_db()
    collection = db["notices"]
    await ensure_indexes(collection)

    fetcher = Fetcher(delay_ms=500)

    # Query DB for notices within the time window (floored by SERVICE_START_DATE)
    window_cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).strftime("%Y-%m-%d")
    cutoff_date_str = max(SERVICE_START_DATE, window_cutoff)

    cursor = collection.find(
        {"date": {"$gte": cutoff_date_str}, "isDeleted": {"$ne": True}},
        {"articleNo": 1, "sourceId": 1, "detailPath": 1,
         "contentHash": 1, "title": 1, "consecutiveFailures": 1},
    )

    # Group by sourceId
    by_dept: dict[str, list[dict[str, Any]]] = {}
    async for doc in cursor:
        dept_id = doc["sourceId"]
        by_dept.setdefault(dept_id, []).append(doc)

    # Build department lookup
    dept_lookup: dict[str, dict[str, Any]] = {d["id"]: d for d in departments}

    if dept_filter:
        valid_ids = set(dept_lookup)
        unknown = [did for did in dept_filter if did not in valid_ids]
        if unknown:
            raise ValueError(
                f"Unknown department ID(s) in CRAWL_SOURCE_FILTER: {unknown}. "
                f"Check sources.json for valid IDs."
            )
        by_dept = {k: v for k, v in by_dept.items() if k in dept_filter}

    logger.info(
        "update_check_starting",
        departments=len(by_dept),
        total_notices=sum(len(v) for v in by_dept.values()),
        window_days=window_days,
    )

    sem = asyncio.Semaphore(5)
    results: list[UpdateCheckResult] = []

    async def check_with_sem(dept_id: str, notices: list[dict]) -> UpdateCheckResult:
        async with sem:
            dept = dept_lookup.get(dept_id)
            if not dept:
                logger.warning("unknown_dept_id", dept_id=dept_id)
                return UpdateCheckResult(source_id=dept_id)
            return await _check_department(
                dept, notices, collection, fetcher, logger,
            )

    tasks = [check_with_sem(dept_id, notices) for dept_id, notices in by_dept.items()]
    settled = await asyncio.gather(*tasks, return_exceptions=True)

    for r in settled:
        if isinstance(r, UpdateCheckResult):
            results.append(r)
        else:
            logger.error("update_check_dept_failed", error=str(r))

    logger.info(
        "update_check_summary",
        departments=len(results),
        total_checked=sum(r.total_checked for r in results),
        total_content_changed=sum(r.content_changed for r in results),
        total_backfilled=sum(r.hash_backfilled for r in results),
        total_errors=sum(r.fetch_errors for r in results),
        total_not_found=sum(r.not_found for r in results),
        total_soft_deleted=sum(r.soft_deleted for r in results),
    )

    await fetcher.close()
    return results


async def _check_department(
    dept: dict[str, Any],
    notices: list[dict[str, Any]],
    collection: Any,
    fetcher: Fetcher,
    logger: Any,
) -> UpdateCheckResult:
    start = time.monotonic()
    result = UpdateCheckResult(source_id=dept["id"])

    strategy_cls = STRATEGY_MAP.get(dept["strategy"])
    if not strategy_cls:
        logger.error("unknown_strategy", dept_id=dept["id"], strategy=dept["strategy"])
        return result

    strategy = strategy_cls(fetcher)
    not_found_docs: list[dict[str, Any]] = []

    for doc in notices:
        detail_path = doc.get("detailPath", "")
        if not detail_path:
            result.skipped_no_detail += 1
            continue

        try:
            detail = await strategy.crawl_detail(
                {"articleNo": doc["articleNo"], "detailPath": detail_path}, dept,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                not_found_docs.append(doc)
                continue
            logger.warning(
                "update_check_fetch_failed",
                articleNo=doc["articleNo"],
                dept_id=dept["id"],
                error=str(exc),
            )
            result.fetch_errors += 1
            continue
        except Exception as exc:
            logger.warning(
                "update_check_fetch_failed",
                articleNo=doc["articleNo"],
                dept_id=dept["id"],
                error=str(exc),
            )
            result.fetch_errors += 1
            continue

        if not detail or not detail.content:
            result.fetch_errors += 1
            continue

        result.total_checked += 1
        doc_filter = {"articleNo": doc["articleNo"], "sourceId": dept["id"]}

        new_clean_html = clean_html(detail.content, dept["baseUrl"])
        new_hash = compute_content_hash(new_clean_html)
        old_hash = doc.get("contentHash")

        # Backfill: old hash is None, just set it
        if old_hash is None:
            now = datetime.now(timezone.utc)
            await collection.update_one(
                doc_filter,
                {"$set": {
                    "contentHash": new_hash,
                    "consecutiveFailures": 0,
                    "crawledAt": now,
                }},
            )
            result.hash_backfilled += 1
            continue

        # No change
        if old_hash == new_hash:
            if doc.get("consecutiveFailures", 0) > 0:
                await collection.update_one(
                    doc_filter, {"$set": {"consecutiveFailures": 0}},
                )
            continue

        # Content changed
        now = datetime.now(timezone.utc)
        edit_entry = {
            "detectedAt": now,
            "oldHash": old_hash,
            "newHash": new_hash,
            "contentChanged": True,
            "source": "tier2",
        }
        normalized_content = normalize_content_urls(detail.content, dept["baseUrl"])
        await collection.update_one(
            doc_filter,
            {
                "$set": {
                    "content": normalized_content,
                    "contentText": detail.contentText,
                    "cleanHtml": new_clean_html,
                    "contentHash": new_hash,
                    "consecutiveFailures": 0,
                    "crawledAt": now,
                },
                "$push": {
                    "editHistory": {
                        "$each": [edit_entry],
                        "$slice": -20,
                    },
                },
                "$inc": {"editCount": 1},
            },
        )
        result.content_changed += 1

    # 2-pass: 404 처리 — 대량 404 안전장치 (최소 5건 이상일 때만 비율 판정)
    result.not_found = len(not_found_docs)
    total_attempted = result.total_checked + result.not_found + result.fetch_errors
    mass_404 = total_attempted >= 5 and result.not_found / total_attempted > 0.5
    if mass_404:
        logger.error(
            "mass_404_detected",
            source_id=dept["id"],
            not_found=result.not_found,
            total_attempted=total_attempted,
        )
    else:
        for doc in not_found_docs:
            was_deleted = doc.get("isDeleted", False)
            updated = await collection.find_one_and_update(
                {"articleNo": doc["articleNo"], "sourceId": dept["id"]},
                [
                    {"$set": {
                        "consecutiveFailures": {
                            "$add": [{"$ifNull": ["$consecutiveFailures", 0]}, 1]
                        },
                    }},
                    {"$set": {
                        "isDeleted": {
                            "$cond": {
                                "if": {"$gte": ["$consecutiveFailures", 3]},
                                "then": True,
                                "else": {"$ifNull": ["$isDeleted", False]},
                            }
                        },
                    }},
                ],
                return_document=ReturnDocument.AFTER,
            )
            if updated and updated.get("isDeleted") and not was_deleted:
                result.soft_deleted += 1

    result.elapsed_seconds = round(time.monotonic() - start, 2)
    logger.info(
        "update_check_dept_done",
        source_id=result.source_id,
        total_checked=result.total_checked,
        content_changed=result.content_changed,
        hash_backfilled=result.hash_backfilled,
        fetch_errors=result.fetch_errors,
        skipped_no_detail=result.skipped_no_detail,
        not_found=result.not_found,
        soft_deleted=result.soft_deleted,
        elapsed_seconds=result.elapsed_seconds,
    )

    # Anomaly detection: backfill 제외 후 변경 비율 체크
    checked_non_backfill = result.total_checked - result.hash_backfilled
    if checked_non_backfill > 0:
        change_rate = result.content_changed / checked_non_backfill
        if change_rate > 0.8:
            logger.error(
                "likely_determinism_bug",
                source_id=result.source_id,
                rate=round(change_rate, 2),
                content_changed=result.content_changed,
                checked=checked_non_backfill,
            )
        elif change_rate > 0.3:
            logger.warning(
                "high_change_rate",
                source_id=result.source_id,
                rate=round(change_rate, 2),
                content_changed=result.content_changed,
                checked=checked_non_backfill,
            )

    return result
