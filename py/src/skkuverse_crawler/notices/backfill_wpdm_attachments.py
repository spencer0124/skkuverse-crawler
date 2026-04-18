"""Backfill WPDM attachment URLs for cheme (wordpress-api strategy).

Replaces landing-page URLs (``/download/{slug}/``) with actual download
URLs (``?wpdmdl={id}``) by re-fetching posts from the WP REST API.

Usage (from py/):
    python -m skkuverse_crawler backfill-wpdm-attachments              # dry-run
    python -m skkuverse_crawler backfill-wpdm-attachments --apply
    python -m skkuverse_crawler backfill-wpdm-attachments --apply --limit 5
"""

from __future__ import annotations

import json

from ..shared.db import close_client, get_db
from ..shared.fetcher import Fetcher
from ..shared.logger import get_logger
from .config.loader import load_and_validate
from .strategies.wordpress_api import WordPressApiStrategy

logger = get_logger("backfill_wpdm_attachments")

DEPT_ID = "cheme"


def _get_cheme_config() -> dict | None:
    for d in load_and_validate():
        if d["id"] == DEPT_ID:
            return d
    return None


async def run(
    *,
    apply: bool,
    limit: int | None = None,
) -> int:
    """Return an exit code (0 success, 1 aborted, 2 partial)."""
    from ..shared.config import init_config

    cfg = init_config(force=True)

    cheme_cfg = _get_cheme_config()
    if not cheme_cfg:
        logger.error("cheme_config_not_found")
        return 1

    db = await get_db()
    collection = db["notices"]

    match = {
        "sourceDeptId": DEPT_ID,
        "attachments": {
            "$elemMatch": {
                "url": {"$regex": "/download/", "$not": {"$regex": "wpdmdl="}},
            },
        },
    }

    pre_count = await collection.count_documents(match)
    logger.info(
        "pre_count",
        db=cfg.mongo_db_name,
        env=cfg.env.value,
        matched=pre_count,
        limit=limit,
    )

    if pre_count == 0:
        logger.info("nothing_to_do")
        await close_client()
        return 0

    if not apply:
        logger.info("dry_run", note="pass --apply to actually update")
        await close_client()
        return 0

    prompt = (
        f"\n  DB: {cfg.mongo_db_name}  ({cfg.env.value})\n"
        f"  matched: {pre_count} docs\n"
        f"  dept:    {DEPT_ID}\n"
        f"  limit:   {limit if limit is not None else 'all'}\n\n"
        f"Re-fetch and fix WPDM attachment URLs? [yes/N]: "
    )
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        answer = ""
    if answer != "yes":
        logger.info("aborted_by_user")
        await close_client()
        return 1

    fetcher = Fetcher(delay_ms=500)
    strategy = WordPressApiStrategy(fetcher)

    updated = 0
    skipped = 0
    failed = 0

    cursor = collection.find(match).batch_size(50)
    async for doc in cursor:
        if limit is not None and updated >= limit:
            break

        article_no = doc.get("articleNo")
        try:
            url = (
                f"{cheme_cfg['baseUrl']}/?rest_route=/wp/v2/posts/{article_no}"
                f"&_fields=content"
            )
            response = await fetcher.fetch(url)
            post = json.loads(response)
            content_html = (post.get("content") or {}).get("rendered", "")
            if not content_html:
                logger.warning("empty_content", articleNo=article_no)
                skipped += 1
                continue

            new_attachments = strategy._extract_attachments(
                content_html, cheme_cfg["baseUrl"]
            )
            if not new_attachments:
                logger.warning("no_attachments_found", articleNo=article_no)
                skipped += 1
                continue

            await collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {"attachments": new_attachments}},
            )
            updated += 1

        except Exception as exc:
            logger.error(
                "update_failed",
                articleNo=article_no,
                error=str(exc),
            )
            failed += 1

        total = updated + skipped + failed
        if total % 10 == 0:
            logger.info(
                "progress",
                total=total,
                updated=updated,
                skipped=skipped,
                failed=failed,
            )

    await fetcher.close()
    logger.info("done", updated=updated, skipped=skipped, failed=failed)
    await close_client()
    return 0 if failed == 0 else 2
