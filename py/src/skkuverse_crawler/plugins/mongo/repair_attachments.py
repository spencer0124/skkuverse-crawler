"""One-off repair of attachment links that were stored broken.

Two populations, two different repairs, and they are different because the
attachments failed for different reasons:

- **custom-php (cal)** — NFUpload serves a file only to a request carrying a
  ``Referer``. The strategy never stored one, so the server proxy had nothing
  to forward and every download came back as ``alert("Access denied!!")``.
  Nothing was fetched wrong; a field was simply missing. The detail-page URL
  is already on the document as ``sourceUrl``, so this repairs **from stored
  data, with no network**.

- **jsp-dorm (dorm)** — ``attach_no`` is not a stable identifier. The board
  reissues it when a post is edited, which leaves stored links pointing at
  nothing or, worse, at a *different* file: production held one labelled
  "2026 Fall Semester Dormitory Admission Guidance.pdf" whose id had been
  reassigned to a fee-payment document, and the download silently returned
  that instead. Only the live page knows the current id, so this one
  **refetches**.

Tier-2 now writes ``attachments`` alongside the content fields, which stops
both from recurring on any notice it touches — but Tier-2 only writes when
the content hash moves, and a rotated ``attach_no`` does not move it. Hence
this pass, for the documents already in that state.

Deliberately not a permanent command. Like ``repair-dimensions``, it drains
a known population once; when that population is zero it should be deleted,
the way the ``backfill-*`` commands were.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...modules.notices.strategies import STRATEGY_MAP
from ...shared.logger import get_logger

logger = get_logger("attachment_repair")

# What is wrong with each population, and therefore how to fix it.
# A strategy absent from this table is not repaired at all — this is a
# targeted drain, not a corpus-wide refetch.
REFERER_BACKFILL = "referer"   # offline: fill the missing field from sourceUrl
REFETCH = "refetch"            # online: re-read the live detail page

REPAIR_MODES: dict[str, str] = {
    "custom-php": REFERER_BACKFILL,
    "jsp-dorm": REFETCH,
}

PROJECTION = {
    "articleNo": 1, "sourceId": 1, "sourceUrl": 1, "detailPath": 1, "attachments": 1,
}


@dataclass
class AttachmentRepairReport:
    scanned: int = 0
    repaired: int = 0
    already_consistent: int = 0
    # Refetch found the notice gone or unparseable. Counted, never written:
    # replacing real attachments with an empty list because a fetch failed
    # would destroy the only record of what the notice used to carry.
    unfetchable: int = 0
    by_source: dict[str, int] = field(default_factory=dict)
    samples: list[dict[str, Any]] = field(default_factory=list)


def backfill_referer(
    attachments: list[dict[str, str]], source_url: str,
) -> list[dict[str, str]] | None:
    """Add the detail-page URL as ``referer``. None when nothing changes.

    Idempotent by construction: an attachment that already carries a referer
    is returned untouched, so a second run reports zero repairs. An empty
    ``source_url`` yields no change rather than an empty referer, which
    would satisfy the validator's presence check while fixing nothing.
    """
    if not source_url:
        return None
    updated = [
        att if att.get("referer") else {**att, "referer": source_url}
        for att in attachments
    ]
    return updated if updated != attachments else None


async def _refetch_attachments(
    doc: dict[str, Any], dept: dict[str, Any], fetcher: Any,
) -> list[dict[str, str]] | None:
    """Read the current attachment list off the live detail page."""
    strategy_cls = STRATEGY_MAP.get(dept["strategy"])
    if strategy_cls is None:
        return None
    strategy = strategy_cls(fetcher)
    detail = await strategy.crawl_detail(
        {"articleNo": doc["articleNo"], "detailPath": doc.get("detailPath", "")},
        dept,
    )
    return detail.attachments if detail is not None else None


async def repair_attachments(
    *,
    dept_filter: tuple[str, ...] | None = None,
    limit: int | None = None,
    apply: bool = False,
    force_refetch: bool = False,
    sample_size: int = 5,
) -> AttachmentRepairReport:
    """Repair stored attachment links. Writes only with ``apply``.

    Reports what it would do either way, so a dry run measures the damage
    rather than promising to fix it.

    ``force_refetch`` overrides the per-strategy mode for the third failure
    the offline repairs cannot see: the source deleted the files. cal-grad
    1353 is the case — its detail page now carries no attachment links at
    all, so its stored links are valid-looking URLs to nothing. Only the
    live page can say so, and nothing else will: Tier-2 refreshes
    attachments but only when the *content* hash moves, and removing a file
    does not touch the body. Opt-in because it spends a request per notice.
    """
    from ...modules.notices.config.loader import load_and_validate
    from ...shared.db import get_db
    from ...shared.fetcher import Fetcher

    departments = {d["id"]: d for d in load_and_validate()}
    repairable = {
        dept_id for dept_id, dept in departments.items()
        if dept.get("strategy") in REPAIR_MODES
    }
    if dept_filter:
        requested = set(dept_filter)
        skipped = requested - repairable
        if skipped:
            # Loud, because silence here reads as "those were already fine".
            logger.warning("no_repair_mode_for_source", sources=sorted(skipped))
        repairable &= requested

    report = AttachmentRepairReport()
    if not repairable:
        logger.info("repair_attachments_finished", applied=apply, scanned=0)
        return report

    db = await get_db()
    collection = db["notices"]
    # Same shape as the attachment auditor's scan: a notice with no
    # attachments has nothing to repair, and refetching it would be a
    # request spent to confirm an empty list is still empty.
    query: dict[str, Any] = {
        "sourceId": {"$in": sorted(repairable)},
        "attachments": {"$exists": True, "$ne": []},
    }

    cursor = collection.find(query, PROJECTION)
    if limit:
        cursor = cursor.limit(limit)

    fetcher = Fetcher(delay_ms=500)
    try:
        async for doc in cursor:
            report.scanned += 1
            dept = departments[doc["sourceId"]]
            attachments = doc.get("attachments") or []

            offline = (
                REPAIR_MODES[dept["strategy"]] == REFERER_BACKFILL and not force_refetch
            )
            if offline:
                repaired = backfill_referer(attachments, doc.get("sourceUrl", ""))
            else:
                fetched = await _refetch_attachments(doc, dept, fetcher)
                if fetched is None:
                    report.unfetchable += 1
                    continue
                repaired = fetched if fetched != attachments else None

            if repaired is None:
                report.already_consistent += 1
                continue

            source_id = doc["sourceId"]
            report.by_source[source_id] = report.by_source.get(source_id, 0) + 1
            if len(report.samples) < sample_size:
                report.samples.append({
                    "sourceId": source_id,
                    "articleNo": doc["articleNo"],
                    "before": attachments[:2],
                    "after": repaired[:2],
                })

            report.repaired += 1
            if apply:
                # No editHistory entry and no crawledAt bump: this repairs a
                # link the crawl got wrong, it does not observe an edit at
                # the source. Recording it as one would be a lie in the data.
                await collection.update_one(
                    {"articleNo": doc["articleNo"], "sourceId": source_id},
                    {"$set": {"attachments": repaired}},
                )
    finally:
        await fetcher.close()

    logger.info(
        "repair_attachments_finished",
        applied=apply,
        scanned=report.scanned,
        repaired=report.repaired,
        already_consistent=report.already_consistent,
        unfetchable=report.unfetchable,
        by_source=report.by_source,
    )
    return report
