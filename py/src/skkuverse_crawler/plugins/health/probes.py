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


def bus_probe() -> CoverageProbe:
    """The bus family's half of a probe.

    No ``inserted_since``, deliberately — see ``CoverageProbe``. The bus
    modules upsert a fixed set of document ids forever, so there is no
    24-hour intake number to report and reporting 0 would read as one.

    ``enabled_ids`` is the half that matters and is load-bearing:
    ``run_daily_summary`` keeps only the failing sources whose id a probe
    claims. Without this, a bus poller stuck down for a day would be
    filtered OUT of the 09:00 message — the one place someone would look.

    Cheap enough to install unconditionally: three enum values, no
    credentials, no I/O. That is what lets a notices-only container still
    report on the bus process it is not running.
    """
    return CoverageProbe(name="bus", enabled_ids=_bus_enabled_ids)


def _bus_enabled_ids() -> set[str]:
    from ...modules.bus.sources import BusSource

    return {source.value for source in BusSource}


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
