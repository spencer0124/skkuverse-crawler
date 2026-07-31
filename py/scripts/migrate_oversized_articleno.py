"""One-off migration: shrink oversized (BSON Long) articleNo to signed int32.

Context: webflow-skku sources (e.g. ftm-undergrad / 영상학과) have no numeric
article id, so the strategy synthesizes articleNo by hashing the URL slug. The
original 56-bit hash exceeded 2^31, so PyMongo stored it as a BSON Long, which
the API serialized as {high,low,unsigned}; the mobile app coerced that object to
0 and every detail link 404'd. The strategy now emits a 31-bit hash (fits BSON
Int32 -> plain JSON number). This migrates EXISTING docs in place: recompute each
doc's articleNo from its slug with the new hash. Content / summaries are
untouched -- only the articleNo key changes.

Safety:
  - Re-derives the slug from detailPath and verifies the OLD 56-bit hash matches
    the stored articleNo before touching anything; aborts (no writes) on any
    mismatch, out-of-range value, or duplicate new id.
  - Dry-run by default; --apply prompts for an explicit `yes`.

IMPORTANT: deploy the updated crawler code to the target env BEFORE running with
--apply, otherwise the next crawl recomputes the old 56-bit hash, finds no match,
and re-inserts duplicate broken docs.

Usage (from py/):
    python scripts/migrate_oversized_articleno.py --env development
    python scripts/migrate_oversized_articleno.py --env development --apply
    python scripts/migrate_oversized_articleno.py --env production --apply
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys

from skkuverse_crawler.modules.notices.strategies.webflow_skku import slug_to_article_no
from skkuverse_crawler.shared.config import init_config
from skkuverse_crawler.shared.db import close_client, get_db
from skkuverse_crawler.shared.logger import configure_logging, get_logger

INT32_MAX = 2**31  # exclusive upper bound for the signed-int32 positive range


def _old_hash(slug: str) -> int:
    # The pre-fix 56-bit hash, kept here only to confirm we recovered the exact
    # slug the original crawl used (its hash must equal the stored articleNo).
    return int(hashlib.blake2b(slug.encode(), digest_size=7).hexdigest(), 16)


def _slug_of(detail_path: str) -> str:
    # Mirrors WebflowSkkuStrategy.crawl_list: slug = last path segment.
    return detail_path.rstrip("/").rsplit("/", 1)[-1] or detail_path


async def run(source: str, apply: bool) -> int:
    cfg = init_config(force=True)
    configure_logging(cfg)
    logger = get_logger("migrate_oversized_articleno")

    db = await get_db()
    collection = db["notices"]

    docs = await collection.find({"sourceId": source}).to_list(length=None)
    logger.info(
        "scanned", db=cfg.mongo_db_name, env=cfg.env.value, source=source, count=len(docs)
    )
    if not docs:
        logger.info("nothing_to_do")
        await close_client()
        return 0

    plan: list[tuple[object, int, int]] = []  # (_id, old, new)
    seen_new: dict[int, object] = {}
    problems = 0
    for d in docs:
        old = d.get("articleNo")
        detail_path = d.get("detailPath") or d.get("sourceUrl") or ""
        slug = _slug_of(detail_path)
        new = slug_to_article_no(slug)
        slug_verified = _old_hash(slug) == old
        in_range = 0 < new < INT32_MAX
        dup = new in seen_new
        seen_new[new] = d["_id"]
        status = "ok" if (slug_verified and in_range and not dup) else "PROBLEM"
        if status != "ok":
            problems += 1
        print(
            f"  [{status}] {old} -> {new}  slug={slug!r}  "
            f"slug_verified={slug_verified} in_int32={in_range} dup={dup}"
        )
        plan.append((d["_id"], old, new))

    if problems:
        logger.error(
            "aborting_no_writes",
            problems=problems,
            note="slug/old-hash mismatch, out-of-range, or duplicate new id",
        )
        await close_client()
        return 1

    if not apply:
        logger.info("dry_run", note="pass --apply to write")
        await close_client()
        return 0

    prompt = (
        f"\n  DB: {cfg.mongo_db_name} ({cfg.env.value})\n"
        f"  source: {source}\n"
        f"  docs: {len(plan)} articleNo rewrites (Long -> int32)\n\n"
        f"Apply? [yes/N]: "
    )
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        answer = ""
    if answer != "yes":
        logger.info("aborted_by_user")
        await close_client()
        return 1

    modified = 0
    for _id, _old, new in plan:
        res = await collection.update_one({"_id": _id}, {"$set": {"articleNo": new}})
        modified += res.modified_count
    logger.info("updated", modified=modified)

    remaining = await collection.count_documents(
        {"sourceId": source, "articleNo": {"$gte": INT32_MAX}}
    )
    logger.info("post_check", oversized_remaining=remaining)
    await close_client()
    return 0 if remaining == 0 else 2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env",
        choices=("production", "development", "test"),
        help="Override CRAWLER_ENV before loading config.",
    )
    parser.add_argument(
        "--source",
        default="ftm-undergrad",
        help="sourceId to migrate (default: ftm-undergrad).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually rewrite articleNo. Without this flag the script only reports the plan.",
    )
    args = parser.parse_args()

    if args.env:
        os.environ["CRAWLER_ENV"] = args.env

    sys.exit(asyncio.run(run(source=args.source, apply=args.apply)))


if __name__ == "__main__":
    main()
