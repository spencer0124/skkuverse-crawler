"""Concrete coverage probes, one per module family.

Kept out of ``module.py`` so that the summary module itself stays
family-agnostic: importing this pulls in the notices source loader, and
the module that reports "is the crawler healthy" should not gain a
notices dependency just by being imported.

The plugins → modules edge here is the sanctioned kind (adr-006): a
plugin may know about a module, never the reverse.
"""

from __future__ import annotations

from datetime import datetime

from bson import ObjectId

from ...shared.db import get_db
from .module import CoverageProbe


def notices_probe() -> CoverageProbe:
    return CoverageProbe(
        name="notices",
        enabled_ids=_notices_enabled_ids,
        inserted_since=_notices_inserted_since,
    )


def _notices_enabled_ids() -> set[str]:
    from ...modules.notices.config.loader import load_and_validate

    return {
        d["id"]
        for d in load_and_validate()
        if d.get("crawlAvailable") and d.get("crawlEnabled")
    }


async def _notices_inserted_since(cutoff: datetime) -> int:
    """Counted through the ObjectId's embedded timestamp rather than a
    field: no schema change, and unlike ``crawledAt`` it is not refreshed
    by the touch updates an unchanged notice generates every crawl."""
    db = await get_db()
    return await db["notices"].count_documents(
        {"_id": {"$gte": ObjectId.from_datetime(cutoff)}}
    )
