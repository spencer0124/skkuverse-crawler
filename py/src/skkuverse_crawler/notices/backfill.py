"""One-shot backfill for cleanHtml / contentText / cleanMarkdown.

Re-runs `clean_html()` on the stored `content` field of every notice so
that improvements to the cleaner pipeline (and the new Markdown converter)
apply to historical documents without needing to re-fetch each source.

Safe to run repeatedly: `clean_html()` is idempotent on absolute URLs,
which is what the `content` field already contains thanks to
`normalize_content_urls()` at crawl time.

Usage (from py/):
    python -m skkuverse_crawler backfill-content                     # dry-run
    python -m skkuverse_crawler backfill-content --apply
    python -m skkuverse_crawler backfill-content --apply --dept cheme
    python -m skkuverse_crawler backfill-content --apply --limit 10
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

from ..shared.db import close_client, get_db
from ..shared.html_cleaner import clean_html
from ..shared.html_to_markdown import html_to_markdown
from ..shared.logger import get_logger
from .config.loader import load_and_validate
from .hashing import compute_content_hash
from .normalizer import _text_from_clean_html

logger = get_logger("backfill_content")

MAX_CONTENT_BYTES = 5 * 1024 * 1024  # 5MB — matches normalizer.MAX_CONTENT_BYTES


def _base_url_map() -> dict[str, str]:
    """Map `sourceDeptId` → `baseUrl` from departments.json."""
    return {d["id"]: d["baseUrl"] for d in load_and_validate()}


def _rebuild_source_url(doc: dict[str, Any], base_url: str) -> str | None:
    """Recompute ``sourceUrl`` from stored ``detailPath`` + ``base_url``.

    Uses the same logic as ``normalizer.build_notice`` so future crawls and
    backfill produce identical URLs.  Returns ``None`` when the existing
    ``sourceUrl`` is already correct (no update needed).
    """
    detail_path = doc.get("detailPath", "")
    if not detail_path:
        return None

    if detail_path.startswith("http"):
        new_url = detail_path
    elif detail_path.startswith("?"):
        new_url = f"{base_url}{detail_path}"
    else:
        new_url = urljoin(base_url, detail_path)

    return new_url if new_url != doc.get("sourceUrl") else None


def _regenerate(doc: dict[str, Any], base_url: str) -> dict[str, Any] | None:
    """Rebuild cleanHtml/contentText/cleanMarkdown/sourceUrl from a document.

    Returns a ``$set`` payload or ``None`` if the doc should be skipped.
    """
    content = doc.get("content")
    has_content = isinstance(content, str) and bool(content)

    new_source_url = _rebuild_source_url(doc, base_url)

    if not has_content and not new_source_url:
        return None

    payload: dict[str, Any] = {"backfilledAt": datetime.now(timezone.utc)}

    if new_source_url:
        payload["sourceUrl"] = new_source_url

    if has_content:
        cleaned = clean_html(content, base_url)
        if cleaned and len(cleaned.encode()) > MAX_CONTENT_BYTES:
            logger.warning(
                "oversized_content_dropped",
                articleNo=doc.get("articleNo"),
                dept=doc.get("sourceDeptId"),
                size=len(cleaned.encode()),
            )
            cleaned = None

        if cleaned:
            content_text: str | None = _text_from_clean_html(cleaned)
        else:
            content_text = doc.get("contentText")

        clean_markdown = html_to_markdown(cleaned)

        payload.update({
            "cleanHtml": cleaned,
            "contentText": content_text,
            "cleanMarkdown": clean_markdown,
            "contentHash": compute_content_hash(cleaned),
        })

    return payload


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

    base_urls = _base_url_map()

    match: dict[str, Any] = {"$or": [{"content": {"$ne": None}}, {"detailPath": {"$exists": True}}]}
    if dept_filter:
        match["sourceDeptId"] = {"$in": list(dept_filter)}

    pre_count = await collection.count_documents(match)
    logger.info(
        "pre_count",
        db=cfg.mongo_db_name,
        env=cfg.env.value,
        matched=pre_count,
        dept_filter=list(dept_filter) if dept_filter else None,
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
        f"  fields:  sourceUrl, cleanHtml, contentText, cleanMarkdown, contentHash, backfilledAt\n"
        f"  limit:   {limit if limit is not None else 'all'}\n\n"
        f"Regenerate these fields? [yes/N]: "
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
        if limit is not None and updated + skipped + failed >= limit:
            break

        dept_id = doc.get("sourceDeptId")
        base_url = base_urls.get(dept_id, "")
        if not base_url:
            logger.warning("missing_base_url", articleNo=doc.get("articleNo"), dept=dept_id)
            skipped += 1
            continue

        try:
            payload = _regenerate(doc, base_url)
        except Exception as exc:
            logger.error(
                "regenerate_failed",
                articleNo=doc.get("articleNo"),
                dept=dept_id,
                error=str(exc),
            )
            failed += 1
            continue

        if payload is None:
            skipped += 1
            continue

        try:
            await collection.update_one({"_id": doc["_id"]}, {"$set": payload})
            updated += 1
        except Exception as exc:
            logger.error(
                "update_failed",
                articleNo=doc.get("articleNo"),
                dept=dept_id,
                error=str(exc),
            )
            failed += 1
            continue

        total = updated + skipped + failed
        if total % 100 == 0:
            logger.info(
                "progress",
                total=total,
                updated=updated,
                skipped=skipped,
                failed=failed,
            )

    logger.info(
        "done",
        updated=updated,
        skipped=skipped,
        failed=failed,
    )

    await close_client()
    return 0 if failed == 0 else 2
