from __future__ import annotations

from collections.abc import Mapping, Sequence

from motor.motor_asyncio import AsyncIOMotorCollection

from ...core.ports import SeenRecord


class MongoSeenIndex:
    """SeenIndex over the notices collection.

    lookup carries dedup.find_existing_meta's body verbatim; the one
    sanctioned deviation is returning SeenRecord instead of raw dicts.
    """

    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._collection = collection

    async def lookup(
        self, source_id: str, article_nos: Sequence[int]
    ) -> Mapping[int, SeenRecord]:
        cursor = self._collection.find(
            {"sourceId": source_id, "articleNo": {"$in": article_nos}},
            {"articleNo": 1, "title": 1, "date": 1, "contentHash": 1},
        )
        result: dict[int, SeenRecord] = {}
        async for doc in cursor:
            result[doc["articleNo"]] = SeenRecord(
                article_no=doc["articleNo"],
                title=doc["title"],
                date=doc["date"],
                content_hash=doc.get("contentHash"),
            )
        return result
