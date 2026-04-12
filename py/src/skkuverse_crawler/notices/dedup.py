from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection

from .models import Notice, NoticeListItem


async def ensure_indexes(collection: AsyncIOMotorCollection) -> None:
    await collection.create_index(
        [("articleNo", 1), ("sourceDeptId", 1)],
        unique=True,
    )
    await collection.create_index(
        [("sourceDeptId", 1), ("date", -1)],
    )


async def find_existing_meta(
    collection: AsyncIOMotorCollection,
    source_dept_id: str,
    article_nos: list[int],
) -> dict[int, dict[str, Any]]:
    cursor = collection.find(
        {"sourceDeptId": source_dept_id, "articleNo": {"$in": article_nos}},
        {"articleNo": 1, "title": 1, "date": 1, "contentHash": 1},
    )
    result: dict[int, dict[str, Any]] = {}
    async for doc in cursor:
        result[doc["articleNo"]] = {
            "articleNo": doc["articleNo"],
            "title": doc["title"],
            "date": doc["date"],
            "contentHash": doc.get("contentHash"),
        }
    return result


def has_changed(item: NoticeListItem, existing: dict[str, Any]) -> bool:
    if item.date != existing["date"]:
        return True
    new_title = item.title
    old_title = existing["title"]
    if new_title == old_title:
        return False
    # Truncated list title (ends with "...") that matches the DB's full
    # title prefix is NOT a real change — the list page just shows a
    # shorter version than the detail-page title stored in the DB.
    if new_title.endswith("..."):
        prefix = new_title[:-3]
        if old_title.startswith(prefix):
            return False
    return True


def should_continue(
    page_items: list[NoticeListItem],
    existing_meta: dict[int, dict[str, Any]],
) -> bool:
    return not all(item.articleNo in existing_meta for item in page_items)


async def upsert_notice(
    collection: AsyncIOMotorCollection,
    notice: Notice,
) -> str:
    doc = asdict(notice)
    edit_history = doc.pop("editHistory", [])
    edit_count = doc.pop("editCount", 0)
    is_deleted = doc.pop("isDeleted", False)
    consecutive_failures = doc.pop("consecutiveFailures", 0)
    result = await collection.update_one(
        {"articleNo": notice.articleNo, "sourceDeptId": notice.sourceDeptId},
        {
            "$set": doc,
            "$setOnInsert": {
                "editHistory": edit_history,
                "editCount": edit_count,
                "isDeleted": is_deleted,
                "consecutiveFailures": consecutive_failures,
            },
        },
        upsert=True,
    )
    return "inserted" if result.upserted_id is not None else "updated"


async def update_with_history(
    collection: AsyncIOMotorCollection,
    notice: Notice,
    edit_entry: dict[str, Any],
) -> None:
    doc = asdict(notice)
    doc.pop("editHistory", None)
    doc.pop("editCount", None)
    doc.pop("isDeleted", None)
    doc.pop("consecutiveFailures", None)
    await collection.update_one(
        {"articleNo": notice.articleNo, "sourceDeptId": notice.sourceDeptId},
        {
            "$set": doc,
            "$push": {"editHistory": {"$each": [edit_entry], "$slice": -20}},
            "$inc": {"editCount": 1},
        },
    )


async def bulk_touch_notices(
    collection: AsyncIOMotorCollection,
    items: list[dict[str, Any]],
) -> None:
    if not items:
        return
    now = datetime.now(timezone.utc)
    ops = [
        {
            "updateOne": {
                "filter": {"articleNo": item["articleNo"], "sourceDeptId": item["sourceDeptId"]},
                "update": {"$set": {"views": item["views"], "crawledAt": now}},
            }
        }
        for item in items
    ]
    await collection.bulk_write(
        [
            _to_pymongo_op(op) for op in ops
        ],
        ordered=False,
    )


def _to_pymongo_op(op: dict) -> Any:
    from pymongo import UpdateOne
    data = op["updateOne"]
    return UpdateOne(data["filter"], data["update"])


async def find_null_content(
    collection: AsyncIOMotorCollection,
    source_dept_id: str,
) -> list[dict[str, Any]]:
    cursor = collection.find(
        {"sourceDeptId": source_dept_id, "$or": [{"content": None}, {"content": ""}]},
        {"articleNo": 1, "detailPath": 1},
    )
    result = []
    async for doc in cursor:
        result.append({
            "articleNo": doc["articleNo"],
            "detailPath": doc.get("detailPath", ""),
        })
    return result
