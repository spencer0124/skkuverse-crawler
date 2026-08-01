from __future__ import annotations

from collections.abc import Sequence

from motor.motor_asyncio import AsyncIOMotorCollection

from ...core.ports import DetailRef


class MongoWorkSeed:
    """WorkSeed over the notices collection: null-content backfill refs.

    pending_refs carries dedup.find_null_content's body verbatim, mapped
    to DetailRef. Called unconditionally before the page loop — backfill
    runs even in full sweeps (adr-006 §⑫: "FullSweep + WorkSeed"는 불법
    상태가 아니라 현행 프로덕션 동작이다).
    """

    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._collection = collection

    async def pending_refs(self, source_id: str) -> Sequence[DetailRef]:
        cursor = self._collection.find(
            {"sourceId": source_id, "$or": [{"content": None}, {"content": ""}]},
            {"articleNo": 1, "detailPath": 1},
        )
        result = []
        async for doc in cursor:
            result.append(
                DetailRef(
                    article_no=doc["articleNo"],
                    detail_path=doc.get("detailPath", ""),
                )
            )
        return result
