"""One-off cleanup: unset all AI summary fields on notices.

Because the AI summary response schema changed (flat startDate/endDate/location
fields were replaced with periods[] / locations[] arrays in commit da6affc),
the existing mixed-shape summary data should be wiped so that the next
notices-summary run can re-summarize from scratch with the new schema.

The service is not live yet, so no user-visible data is lost. After running
this, find_unsummarized() will pick these notices up on the next cron tick.

Usage (from py/):
    python scripts/cleanup_summary_fields.py                         # dry-run, current env
    python scripts/cleanup_summary_fields.py --env production --apply
    python scripts/cleanup_summary_fields.py --env development --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from skkuverse_crawler.shared.config import init_config
from skkuverse_crawler.shared.db import close_client, get_db
from skkuverse_crawler.shared.logger import configure_logging, get_logger

SUMMARY_FIELDS: tuple[str, ...] = (
    "summary",
    "summaryAt",
    "summaryContentHash",
    "summaryDetails",
    "summaryFailures",
    "summaryModel",
    "summaryOneLiner",
    "summaryType",
    "summaryPeriods",
    "summaryLocations",
    "summaryStartDate",
    "summaryStartTime",
    "summaryEndDate",
    "summaryEndTime",
)


async def run(apply: bool) -> int:
    cfg = init_config(force=True)
    configure_logging()
    logger = get_logger("cleanup_summary_fields")

    db = await get_db()
    collection = db["notices"]

    match = {"$or": [{f: {"$exists": True}} for f in SUMMARY_FIELDS]}

    pre_count = await collection.count_documents(match)
    logger.info(
        "pre_count",
        db=cfg.mongo_db_name,
        env=cfg.env.value,
        matched=pre_count,
        fields=list(SUMMARY_FIELDS),
    )

    if pre_count == 0:
        logger.info("nothing_to_do")
        await close_client()
        return 0

    if not apply:
        logger.info("dry_run", note="pass --apply to actually unset fields")
        await close_client()
        return 0

    prompt = (
        f"\n  DB: {cfg.mongo_db_name}  ({cfg.env.value})\n"
        f"  matched: {pre_count} docs\n"
        f"  fields:  {', '.join(SUMMARY_FIELDS)}\n\n"
        f"Unset these fields on {pre_count} docs? [yes/N]: "
    )
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        answer = ""
    if answer != "yes":
        logger.info("aborted_by_user")
        await close_client()
        return 1

    unset_spec = {f: "" for f in SUMMARY_FIELDS}
    result = await collection.update_many(match, {"$unset": unset_spec})
    logger.info(
        "updated",
        matched=result.matched_count,
        modified=result.modified_count,
    )

    post_count = await collection.count_documents(
        {"$or": [{f: {"$exists": True}} for f in SUMMARY_FIELDS]},
    )
    logger.info("post_count", remaining=post_count)

    await close_client()
    return 0 if post_count == 0 else 2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env",
        choices=("production", "development", "test"),
        help="Override CRAWLER_ENV before loading config.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually unset the fields. Without this flag the script only reports counts.",
    )
    args = parser.parse_args()

    if args.env:
        os.environ["CRAWLER_ENV"] = args.env

    sys.exit(asyncio.run(run(apply=args.apply)))


if __name__ == "__main__":
    main()
