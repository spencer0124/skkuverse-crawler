"""One-off repair of documents Tier-2 damaged before it ran the pipeline.

Until 2026-08-03 the Tier-2 update checker derived a notice's stored
fields by hand: no image probe, and ``contentText`` taken straight from
the strategy. Every notice it touched lost the ``width``/``height`` on its
``<img>`` tags and, with them, the ``{WxH}`` hint the app parses to
reserve an image's space — and got the older, run-on text format back.

**No re-crawl, and no image fetch.** The measurements are already in the
database: Tier-2 rewrote ``cleanHtml`` but never touched ``cleanMarkdown``,
so the stale markdown still carries every ``{WxH}`` it was written with.
Reading them back and re-running the tail of the content pipeline repairs
both problems from stored data alone.

Deliberately not a permanent command. It exists to drain a known
population once; when that population is zero it should be deleted, the
way the ``backfill-*`` commands were.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...modules.notices.normalizer import dimensions_from_markdown
from ...modules.notices.stages import rederive_from_clean_html
from ...shared.logger import get_logger

logger = get_logger("notices_repair")

# Every document Tier-2 has ever written. Narrower than it looks: a
# document the crawl wrote last is already consistent and comes back
# byte-identical, so it costs a derivation and no write.
DAMAGED_QUERY: dict[str, Any] = {"editHistory.source": "tier2"}

PROJECTION = {
    "articleNo": 1, "sourceId": 1,
    "content": 1, "contentText": 1, "cleanHtml": 1, "cleanMarkdown": 1, "contentHash": 1,
}

# Repaired here, and the only fields that may be. `content` is passed
# through the pipeline so the size guard can null it in step with
# cleanHtml, but it is never rewritten from anything.
REPAIRED_FIELDS = ("contentText", "cleanHtml", "cleanMarkdown", "contentHash")


@dataclass
class RepairReport:
    scanned: int = 0
    repaired: int = 0
    already_consistent: int = 0
    # Has images, but the stale markdown holds no measurement for any URL
    # currently in the body — the images were swapped out in the same edit
    # that lost the dimensions, so there is nothing to restore. Counted
    # alongside the others, not instead of them: such a document may still
    # have had its text or hash repaired. The next Tier-2 pass measures
    # those images for real.
    unmeasurable: int = 0
    skipped_no_content: int = 0
    changed_fields: dict[str, int] = field(default_factory=dict)
    samples: list[dict[str, Any]] = field(default_factory=list)


async def repair_lost_dimensions(
    *,
    dept_filter: tuple[str, ...] | None = None,
    limit: int | None = None,
    apply: bool = False,
    sample_size: int = 5,
) -> RepairReport:
    """Re-derive stored fields from stored data. Writes only with ``apply``.

    Reports what it would do either way, so a dry run is a measurement of
    the damage rather than a promise about it.
    """
    from ...shared.db import get_db

    db = await get_db()
    collection = db["notices"]

    query = dict(DAMAGED_QUERY)
    if dept_filter:
        query["sourceId"] = {"$in": list(dept_filter)}

    report = RepairReport()
    cursor = collection.find(query, PROJECTION)
    if limit:
        cursor = cursor.limit(limit)

    async for doc in cursor:
        report.scanned += 1
        stored_html = doc.get("cleanHtml")
        if not stored_html:
            report.skipped_no_content += 1
            continue

        dimensions = dimensions_from_markdown(doc.get("cleanMarkdown"))
        # Counted independently of whether anything else changed: an image
        # with no stored measurement is a fact about this document, not a
        # property of the repair's outcome. Folding it into the
        # already-consistent branch hid it whenever the hash also moved.
        if "<img" in stored_html and not dimensions:
            report.unmeasurable += 1

        fields = await rederive_from_clean_html(
            stored_html,
            content=doc.get("content"),
            dimensions=dimensions,
            fallback_text=doc.get("contentText"),
            source_id=doc["sourceId"],
            article_no=doc["articleNo"],
            log=logger,
        )

        changed = {
            name: getattr(fields, name)
            for name in REPAIRED_FIELDS
            if getattr(fields, name) != doc.get(name)
        }
        if not changed:
            report.already_consistent += 1
            continue

        for name in changed:
            report.changed_fields[name] = report.changed_fields.get(name, 0) + 1
        if len(report.samples) < sample_size:
            report.samples.append({
                "sourceId": doc["sourceId"],
                "articleNo": doc["articleNo"],
                "fields": sorted(changed),
                "restored_dimensions": len(dimensions),
            })

        report.repaired += 1
        if apply:
            # No editHistory entry and no crawledAt bump: this repairs
            # derived fields, it does not observe a change at the source.
            # Recording it as either would be a lie in the data.
            await collection.update_one(
                {"articleNo": doc["articleNo"], "sourceId": doc["sourceId"]},
                {"$set": changed},
            )

    logger.info(
        "repair_finished",
        applied=apply,
        scanned=report.scanned,
        repaired=report.repaired,
        already_consistent=report.already_consistent,
        unmeasurable=report.unmeasurable,
        skipped_no_content=report.skipped_no_content,
        changed_fields=report.changed_fields,
    )
    return report
