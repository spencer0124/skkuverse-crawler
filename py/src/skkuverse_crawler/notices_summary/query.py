from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection


async def ensure_summary_indexes(collection: AsyncIOMotorCollection) -> None:
    await collection.create_index(
        [("summaryAt", 1), ("contentText", 1)],
        name="idx_summary_pending",
        partialFilterExpression={"contentText": {"$exists": True}},
    )


async def find_unsummarized(
    collection: AsyncIOMotorCollection,
    batch_size: int = 50,
) -> list[dict[str, Any]]:
    """Find notices that have content but no summary yet."""
    cursor = collection.find(
        {
            "contentText": {"$nin": [None, ""]},
            "$or": [
                {"summaryAt": None},
                {"summaryAt": {"$exists": False}},
            ],
            "summaryFailures": {"$not": {"$gte": 3}},
        },
        {
            "_id": 1,
            "articleNo": 1,
            "sourceId": 1,
            "title": 1,
            "category": 1,
            "contentText": 1,
            "contentHash": 1,
            "date": 1,
        },
    ).sort("crawledAt", -1).limit(batch_size)

    return [doc async for doc in cursor]


async def find_stale_summaries(
    collection: AsyncIOMotorCollection,
    batch_size: int = 50,
) -> list[dict[str, Any]]:
    """Find notices where content changed after summarization."""
    cursor = collection.find(
        {
            "summaryAt": {"$exists": True, "$ne": None},
            "contentText": {"$nin": [None, ""]},
            "$expr": {"$ne": ["$summaryContentHash", "$contentHash"]},
            "summaryFailures": {"$not": {"$gte": 3}},
        },
        {
            "_id": 1,
            "articleNo": 1,
            "sourceId": 1,
            "title": 1,
            "category": 1,
            "contentText": 1,
            "contentHash": 1,
            "date": 1,
        },
    ).sort("crawledAt", -1).limit(batch_size)

    return [doc async for doc in cursor]
