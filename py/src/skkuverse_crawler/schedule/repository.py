from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection


async def upsert_year(
    collection: AsyncIOMotorCollection,
    year_doc: dict[str, Any],
) -> str:
    """Upsert one academic-year document, skipping writes when unchanged.

    ``_id`` is the academic year (natural key) so corrections replace the whole
    ``events`` array in a single ``$set`` — no stale duplicates. The stored
    ``yearHash`` gates the write: identical hash => no DB write at all.
    Returns "skipped" | "inserted" | "updated".
    """
    year = year_doc["_id"]
    existing = await collection.find_one({"_id": year}, {"yearHash": 1})
    if existing is not None and existing.get("yearHash") == year_doc["yearHash"]:
        return "skipped"

    now = datetime.now(UTC)
    set_doc = {k: v for k, v in year_doc.items() if k != "_id"}
    set_doc["updatedAt"] = now
    result = await collection.update_one(
        {"_id": year},
        {"$set": set_doc, "$setOnInsert": {"crawledAt": now}},
        upsert=True,
    )
    return "inserted" if result.upserted_id is not None else "updated"
