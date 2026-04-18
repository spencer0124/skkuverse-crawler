"""Backfill attachments for skku-standard subdomain departments.

Re-fetches the detail page of notices that have ``attachments: []`` and
re-parses attachments using the (now-corrected) selector from
``departments.json``.

Only targets ``skku-standard`` departments on subdomain sites
(not ``www.skku.edu``) — the ones affected by the selector mismatch.

Usage (from py/):
    python -m skkuverse_crawler backfill-attachments              # dry-run
    python -m skkuverse_crawler backfill-attachments --apply
    python -m skkuverse_crawler backfill-attachments --apply --dept cse-undergrad
    python -m skkuverse_crawler backfill-attachments --apply --limit 50
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..shared.db import close_client, get_db
from ..shared.fetcher import Fetcher
from ..shared.logger import get_logger
from .config.loader import load_and_validate
from .strategies.skku_standard import SkkuStandardStrategy

logger = get_logger("backfill_attachments")

DELAY_BETWEEN_REQUESTS = 0.5  # seconds — be kind to SKKU servers


def _affected_dept_configs() -> dict[str, dict[str, Any]]:
    """Return dept configs for skku-standard subdomain departments."""
    return {
        d["id"]: d
        for d in load_and_validate()
        if d["strategy"] == "skku-standard"
        and "www.skku.edu" not in d["baseUrl"]
    }


async def run(
    *,
    apply: bool,
    dept_filter: tuple[str, ...] | None = None,
    limit: int | None = None,
) -> int:
    """Return an exit code (0 success, 1 aborted, 2 partial)."""
    from ..shared.config import init_config

    cfg = init_config(force=True)

    db = await get_db()
    collection = db["notices"]

    dept_configs = _affected_dept_configs()
    target_ids = list(dept_configs.keys())

    if dept_filter:
        target_ids = [d for d in dept_filter if d in dept_configs]
        if not target_ids:
            logger.info("no_matching_depts", dept_filter=list(dept_filter))
            await close_client()
            return 0

    match: dict[str, Any] = {
        "sourceDeptId": {"$in": target_ids},
        "attachments": {"$size": 0},
    }

    pre_count = await collection.count_documents(match)
    logger.info(
        "pre_count",
        db=cfg.mongo_db_name,
        env=cfg.env.value,
        matched=pre_count,
        target_depts=len(target_ids),
        limit=limit,
    )

    if pre_count == 0:
        logger.info("nothing_to_do")
        await close_client()
        return 0

    if not apply:
        logger.info("dry_run", matched=pre_count, note="pass --apply to actually update")
        await close_client()
        return 0

    prompt = (
        f"\n  DB: {cfg.mongo_db_name}  ({cfg.env.value})\n"
        f"  matched: {pre_count} docs with empty attachments\n"
        f"  depts:   {len(target_ids)} departments\n"
        f"  limit:   {limit if limit is not None else 'all'}\n\n"
        f"Re-fetch and backfill attachments? [yes/N]: "
    )
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        answer = ""
    if answer != "yes":
        logger.info("aborted_by_user")
        await close_client()
        return 1

    fetcher = Fetcher(delay_ms=int(DELAY_BETWEEN_REQUESTS * 1000))
    strategy = SkkuStandardStrategy(fetcher)

    updated = 0
    skipped = 0
    failed = 0
    no_new_attachments = 0

    cursor = collection.find(match).batch_size(50)
    async for doc in cursor:
        if limit is not None and updated >= limit:
            break

        dept_id = doc.get("sourceDeptId")
        dept_config = dept_configs.get(dept_id)
        if not dept_config:
            skipped += 1
            continue

        detail_path = doc.get("detailPath", "")
        article_no = doc.get("articleNo")
        if not detail_path and not article_no:
            skipped += 1
            continue

        try:
            ref = {"articleNo": article_no, "detailPath": detail_path}
            detail = await strategy.crawl_detail(ref, dept_config)
        except Exception as exc:
            logger.error(
                "fetch_failed",
                articleNo=article_no,
                dept=dept_id,
                error=str(exc),
            )
            failed += 1
            continue

        if detail is None or not detail.attachments:
            no_new_attachments += 1
            continue

        try:
            await collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {"attachments": detail.attachments}},
            )
            updated += 1
            logger.debug(
                "updated",
                articleNo=article_no,
                dept=dept_id,
                count=len(detail.attachments),
            )
        except Exception as exc:
            logger.error(
                "update_failed",
                articleNo=article_no,
                dept=dept_id,
                error=str(exc),
            )
            failed += 1

        total = updated + skipped + failed + no_new_attachments
        if total % 50 == 0:
            logger.info(
                "progress",
                total=total,
                updated=updated,
                no_new=no_new_attachments,
                skipped=skipped,
                failed=failed,
            )

        await asyncio.sleep(DELAY_BETWEEN_REQUESTS)

    logger.info(
        "done",
        updated=updated,
        no_new_attachments=no_new_attachments,
        skipped=skipped,
        failed=failed,
    )
    await close_client()
    return 0 if failed == 0 else 2
