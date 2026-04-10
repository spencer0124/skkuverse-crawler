from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..shared.db import get_db
from ..shared.fetcher import Fetcher
from ..shared.html_cleaner import clean_html, normalize_content_urls
from ..shared.logger import get_logger
from .dedup import (
    bulk_touch_notices,
    ensure_indexes,
    find_existing_meta,
    find_null_content,
    has_changed,
    should_continue,
    update_with_history,
    upsert_notice,
)
from .constants import SERVICE_START_DATE
from .hashing import compute_content_hash
from .image_verifier import verify_notice_images
from .models import Notice, NoticeListItem
from .normalizer import build_notice
from .strategies.skku_standard import SkkuStandardStrategy
from .strategies.wordpress_api import WordPressApiStrategy
from .strategies.skkumed_asp import SkkumedAspStrategy
from .strategies.jsp_dorm import JspDormStrategy
from .strategies.custom_php import CustomPhpStrategy
from .strategies.gnuboard import GnuboardStrategy
from .strategies.gnuboard_custom import GnuboardCustomStrategy


_MAX_CONTENT_BYTES = 5 * 1024 * 1024  # 5MB


@dataclass
class CrawlOptions:
    incremental: bool = True
    max_pages: int | None = None
    delay_ms: int | None = None
    dept_filter: tuple[str, ...] | None = None


@dataclass
class DeptResult:
    dept_id: str = ""
    dept_name: str = ""
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    duration_ms: int = 0


STRATEGY_MAP: dict[str, type] = {
    "skku-standard": SkkuStandardStrategy,
    "wordpress-api": WordPressApiStrategy,
    "skkumed-asp": SkkumedAspStrategy,
    "jsp-dorm": JspDormStrategy,
    "custom-php": CustomPhpStrategy,
    "gnuboard": GnuboardStrategy,
    "gnuboard-custom": GnuboardCustomStrategy,
}


async def run_crawl(
    departments: list[dict[str, Any]],
    options: CrawlOptions,
) -> list[DeptResult]:
    crawl_id = uuid.uuid4().hex[:8]
    logger = get_logger("orchestrator", crawl_id=crawl_id)

    db = await get_db()
    collection = db["notices"]
    await ensure_indexes(collection)

    fetcher = Fetcher(delay_ms=options.delay_ms or 500)

    if options.dept_filter:
        valid_ids = {d["id"] for d in departments}
        unknown = [did for did in options.dept_filter if did not in valid_ids]
        if unknown:
            raise ValueError(
                f"Unknown department ID(s) in CRAWL_DEPT_FILTER: {unknown}. "
                f"Check departments.json for valid IDs."
            )
        filtered = [d for d in departments if d["id"] in options.dept_filter]
    else:
        filtered = departments

    if not filtered:
        logger.warning("no_matching_departments", dept_filter=options.dept_filter)
        return []

    sem = asyncio.Semaphore(5)
    results: list[DeptResult] = []

    async def crawl_with_sem(dept: dict) -> DeptResult:
        async with sem:
            return await _crawl_department(dept, collection, fetcher, options, logger)

    tasks = [crawl_with_sem(dept) for dept in filtered]
    settled = await asyncio.gather(*tasks, return_exceptions=True)

    for r in settled:
        if isinstance(r, DeptResult):
            results.append(r)
        else:
            logger.error("department_crawl_failed", error=str(r))

    total_inserted = sum(r.inserted for r in results)
    total_updated = sum(r.updated for r in results)
    total_skipped = sum(r.skipped for r in results)
    total_errors = sum(r.errors for r in results)
    logger.info(
        "crawl_completed",
        departments=len(results),
        total_inserted=total_inserted,
        total_updated=total_updated,
        total_skipped=total_skipped,
        total_errors=total_errors,
    )

    await fetcher.close()
    return results


async def _crawl_department(
    dept: dict[str, Any],
    collection: Any,
    fetcher: Fetcher,
    options: CrawlOptions,
    logger: Any,
) -> DeptResult:
    start = time.monotonic()
    strategy_cls = STRATEGY_MAP.get(dept["strategy"])
    if not strategy_cls:
        raise ValueError(f"Unknown strategy: {dept['strategy']}")

    strategy = strategy_cls(fetcher)
    result = DeptResult(dept_id=dept["id"], dept_name=dept["name"])

    logger.info("starting_department_crawl", dept_id=dept["id"], dept_name=dept["name"])

    # Re-crawl null content
    null_refs = await find_null_content(collection, dept["id"])
    if null_refs:
        logger.info("recrawling_null_content", count=len(null_refs), dept_id=dept["id"])
        for ref in null_refs:
            detail = await strategy.crawl_detail(
                {"articleNo": ref["articleNo"], "detailPath": ref["detailPath"]}, dept
            )
            if detail:
                cleaned = clean_html(detail.content, dept["baseUrl"])
                raw_content = normalize_content_urls(detail.content, dept["baseUrl"])
                if cleaned and len(cleaned.encode()) > _MAX_CONTENT_BYTES:
                    logger.warning(
                        "oversized_content_dropped",
                        articleNo=ref["articleNo"],
                        dept=dept["id"],
                        size=len(cleaned.encode()),
                    )
                    cleaned = None
                    raw_content = None
                await collection.update_one(
                    {"articleNo": ref["articleNo"], "sourceDeptId": dept["id"]},
                    {"$set": {
                        "content": raw_content,
                        "contentText": detail.contentText,
                        "cleanHtml": cleaned,
                        "contentHash": compute_content_hash(cleaned),
                        "attachments": detail.attachments,
                        "crawledAt": datetime.now(timezone.utc),
                    }},
                )
                result.updated += 1

    # Crawl list pages
    max_pages = options.max_pages or (100 if options.incremental else 2500)
    page = 0

    while page < max_pages:
        try:
            list_items = await strategy.crawl_list(dept, page)
        except Exception as exc:
            logger.error("list_fetch_failed", dept_id=dept["id"], page=page, error=str(exc))
            result.errors += 1
            break

        if not list_items:
            logger.info("empty_list_page", dept_id=dept["id"], page=page)
            break

        if all(item.date and item.date < SERVICE_START_DATE for item in list_items):
            logger.info("floor_date_stopping", page=page, dept_id=dept["id"])
            break

        is_first_page = page == 0

        if options.incremental:
            article_nos = [item.articleNo for item in list_items]
            existing_meta = await find_existing_meta(collection, dept["id"], article_nos)
            all_known = not should_continue(list_items, existing_meta)

            if not is_first_page and all_known:
                logger.info("all_known_stopping", page=page)
                break

            if is_first_page and all_known:
                logger.info("all_known_first_page_early_stop")
                await _process_page_smart(
                    list_items, existing_meta, strategy, dept, collection, result, logger
                )
                break

            await _process_page_smart(
                list_items, existing_meta, strategy, dept, collection, result, logger
            )
        else:
            await _process_page_full(list_items, strategy, dept, collection, result, logger)

        page += 1

    result.duration_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "department_crawl_finished",
        dept_id=result.dept_id,
        inserted=result.inserted,
        updated=result.updated,
        skipped=result.skipped,
        errors=result.errors,
        duration_ms=result.duration_ms,
    )
    return result


async def _verify_and_log_images(notice: Notice, dept_id: str) -> None:
    """Best-effort image verification — never raises, only logs."""
    try:
        result = await verify_notice_images(notice.content, notice.sourceUrl)
        if result.broken:
            logger.warning(
                "broken_notice_images",
                articleNo=notice.articleNo,
                dept_id=dept_id,
                checked=result.checked,
                broken_count=len(result.broken),
                broken=result.broken[:5],  # cap log payload
            )
    except Exception as exc:
        logger.warning(
            "image_verify_failed",
            articleNo=notice.articleNo,
            dept_id=dept_id,
            error=str(exc),
        )


async def _process_page_smart(
    list_items: list[NoticeListItem],
    existing_meta: dict[int, dict[str, Any]],
    strategy: Any,
    dept: dict[str, Any],
    collection: Any,
    result: DeptResult,
    logger: Any,
) -> None:
    to_touch: list[dict[str, Any]] = []

    for item in list_items:
        try:
            if item.date and item.date < SERVICE_START_DATE:
                result.skipped += 1
                continue

            existing = existing_meta.get(item.articleNo)

            if existing and not has_changed(item, existing):
                to_touch.append({
                    "articleNo": item.articleNo,
                    "sourceDeptId": dept["id"],
                    "views": item.views,
                })
                result.skipped += 1
                continue

            detail = await strategy.crawl_detail(
                {"articleNo": item.articleNo, "detailPath": item.detailPath}, dept
            )
            notice = build_notice(
                item, detail,
                department=dept["name"],
                source_dept_id=dept["id"],
                base_url=dept["baseUrl"],
            )
            await _verify_and_log_images(notice, dept["id"])

            if not existing:
                action = await upsert_notice(collection, notice)
                if action == "inserted":
                    result.inserted += 1
                else:
                    result.updated += 1
            else:
                logger.info(
                    "change_detected",
                    articleNo=item.articleNo,
                    old_title=existing["title"],
                    new_title=item.title,
                )
                old_hash = existing.get("contentHash")
                new_hash = notice.contentHash
                edit_entry = {
                    "detectedAt": datetime.now(timezone.utc),
                    "oldHash": old_hash,
                    "newHash": new_hash,
                    "oldTitle": existing["title"],
                    "newTitle": item.title,
                    "titleChanged": existing["title"] != item.title,
                    "contentChanged": old_hash is not None and old_hash != new_hash,
                    "source": "tier1",
                }
                await update_with_history(collection, notice, edit_entry)
                result.updated += 1

        except Exception as exc:
            logger.error("process_article_failed", articleNo=item.articleNo, error=str(exc))
            result.errors += 1

    if to_touch:
        await bulk_touch_notices(collection, to_touch)


async def _process_page_full(
    list_items: list[NoticeListItem],
    strategy: Any,
    dept: dict[str, Any],
    collection: Any,
    result: DeptResult,
    logger: Any,
) -> None:
    for item in list_items:
        try:
            if item.date and item.date < SERVICE_START_DATE:
                result.skipped += 1
                continue

            detail = await strategy.crawl_detail(
                {"articleNo": item.articleNo, "detailPath": item.detailPath}, dept
            )
            notice = build_notice(
                item, detail,
                department=dept["name"],
                source_dept_id=dept["id"],
                base_url=dept["baseUrl"],
            )
            await _verify_and_log_images(notice, dept["id"])
            action = await upsert_notice(collection, notice)
            if action == "inserted":
                result.inserted += 1
            else:
                result.updated += 1

        except Exception as exc:
            logger.error("process_article_failed", articleNo=item.articleNo, error=str(exc))
            result.errors += 1
