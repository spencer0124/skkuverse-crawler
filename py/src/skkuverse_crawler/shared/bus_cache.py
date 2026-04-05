from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .db import get_db
from .logger import get_logger

logger = get_logger("bus_cache")

_index_ensured = False


async def _get_collection():  # noqa: ANN202
    db = await get_db()
    return db["bus_cache"]


async def ensure_index() -> None:
    global _index_ensured  # noqa: PLW0603
    if _index_ensured:
        return
    coll = await _get_collection()
    await coll.create_index(
        "_updatedAt", expireAfterSeconds=60, name="ttl_updatedAt"
    )
    _index_ensured = True


async def write(key: str, data: Any) -> None:
    coll = await _get_collection()
    await coll.update_one(
        {"_id": key},
        {"$set": {"data": data, "_updatedAt": datetime.now(timezone.utc)}},
        upsert=True,
    )


async def read(key: str) -> Any:
    coll = await _get_collection()
    doc = await coll.find_one({"_id": key})
    return doc["data"] if doc else None
