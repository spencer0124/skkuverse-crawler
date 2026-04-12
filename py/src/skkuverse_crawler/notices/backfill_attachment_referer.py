"""Backfill `referer` field into gnuboard attachment metadata.

Adds the detail-page URL as ``referer`` to each attachment dict so the
skkuverse-server proxy can establish a PHP session before downloading.

No HTTP requests — purely URL string assembly from stored ``detailPath``
and department config.

Usage (from py/):
    python -m skkuverse_crawler backfill-attachment-referer              # dry-run
    python -m skkuverse_crawler backfill-attachment-referer --apply
    python -m skkuverse_crawler backfill-attachment-referer --apply --dept nano
    python -m skkuverse_crawler backfill-attachment-referer --apply --limit 10
"""

from __future__ import annotations

from typing import Any

from ..shared.db import close_client, get_db
from ..shared.logger import get_logger
from .config.loader import load_and_validate

logger = get_logger("backfill_attachment_referer")

GNUBOARD_STRATEGIES = ("gnuboard", "gnuboard-custom")


def _dept_config_map() -> dict[str, dict[str, Any]]:
    """Map ``sourceDeptId`` -> full department config for gnuboard depts."""
    return {
        d["id"]: d
        for d in load_and_validate()
        if d["strategy"] in GNUBOARD_STRATEGIES
    }


def _build_detail_url(doc: dict[str, Any], dept: dict[str, Any]) -> str:
    """Reconstruct the detail-page URL from stored detailPath + dept config.

    Mirrors the URL construction in gnuboard.py / gnuboard_custom.py
    ``crawl_detail`` methods.
    """
    detail_path = doc.get("detailPath", "")

    if detail_path.startswith("http"):
        return detail_path

    if detail_path.startswith("?"):
        return f"{dept['baseUrl']}{detail_path}"

    # Fallback: construct from config + articleNo
    base = f"{dept['baseUrl']}?{dept['boardParam']}={dept['boardName']}"
    if dept["strategy"] == "gnuboard-custom":
        return f"{base}&mode={dept['detailMode']}&num={doc['articleNo']}"
    return f"{base}&wr_id={doc['articleNo']}"


def _patch_attachments(
    attachments: list[dict[str, str]],
    referer: str,
) -> list[dict[str, str]] | None:
    """Add ``referer`` to each attachment dict. Returns None if unchanged."""
    if all("referer" in a for a in attachments):
        return None
    return [{**a, "referer": referer} for a in attachments]


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

    dept_configs = _dept_config_map()
    gnuboard_ids = list(dept_configs.keys())

    if dept_filter:
        target_ids = [d for d in dept_filter if d in dept_configs]
        if not target_ids:
            logger.info("no_matching_gnuboard_depts", dept_filter=list(dept_filter))
            await close_client()
            return 0
    else:
        target_ids = gnuboard_ids

    match: dict[str, Any] = {
        "sourceDeptId": {"$in": target_ids},
        "attachments": {"$ne": []},
        "attachments.referer": {"$exists": False},
    }

    pre_count = await collection.count_documents(match)
    logger.info(
        "pre_count",
        db=cfg.mongo_db_name,
        env=cfg.env.value,
        matched=pre_count,
        target_depts=target_ids,
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
        f"  depts:   {target_ids}\n"
        f"  limit:   {limit if limit is not None else 'all'}\n\n"
        f"Add referer to attachments? [yes/N]: "
    )
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        answer = ""
    if answer != "yes":
        logger.info("aborted_by_user")
        await close_client()
        return 1

    updated = 0
    skipped = 0
    failed = 0

    cursor = collection.find(match).batch_size(100)
    async for doc in cursor:
        if limit is not None and updated >= limit:
            break

        dept_id = doc.get("sourceDeptId")
        dept = dept_configs.get(dept_id)
        if not dept:
            skipped += 1
            continue

        try:
            referer = _build_detail_url(doc, dept)
            patched = _patch_attachments(doc["attachments"], referer)
        except Exception as exc:
            logger.error(
                "build_referer_failed",
                articleNo=doc.get("articleNo"),
                dept=dept_id,
                error=str(exc),
            )
            failed += 1
            continue

        if patched is None:
            skipped += 1
            continue

        try:
            await collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {"attachments": patched}},
            )
            updated += 1
        except Exception as exc:
            logger.error(
                "update_failed",
                articleNo=doc.get("articleNo"),
                dept=dept_id,
                error=str(exc),
            )
            failed += 1

        total = updated + skipped + failed
        if total % 50 == 0:
            logger.info("progress", total=total, updated=updated, skipped=skipped, failed=failed)

    logger.info("done", updated=updated, skipped=skipped, failed=failed)
    await close_client()
    return 0 if failed == 0 else 2
