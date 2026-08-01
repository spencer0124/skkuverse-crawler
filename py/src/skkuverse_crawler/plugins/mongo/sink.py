from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from motor.motor_asyncio import AsyncIOMotorCollection

from ...core.events import (
    ChangeInfo,
    ContentRefreshed,
    CrawlEvent,
    NoticeCrawled,
    NoticeUnchanged,
)
from ...core.ports import Outcome, SourceSpec

if TYPE_CHECKING:
    # Type-only reverse-layer edge (plugins → modules), sanctioned until
    # Notice's final home is settled (PR 6/7). Must stay type-only.
    from ...modules.notices.models import Notice


async def ensure_indexes(collection: AsyncIOMotorCollection) -> None:
    await collection.create_index(
        [("articleNo", 1), ("sourceId", 1)],
        unique=True,
    )
    await collection.create_index(
        [("sourceId", 1), ("date", -1)],
    )


def _to_pymongo_op(op: dict) -> Any:
    from pymongo import UpdateOne
    data = op["updateOne"]
    return UpdateOne(data["filter"], data["update"])


def _edit_entry(change: ChangeInfo) -> dict[str, Any]:
    """The stored tier-1 edit history entry. detectedAt and the "tier1"
    marker are storage concerns; everything else arrives via ChangeInfo."""
    return {
        "detectedAt": datetime.now(timezone.utc),
        "oldHash": change.old_hash,
        "newHash": change.new_hash,
        "oldTitle": change.old_title,
        "newTitle": change.new_title,
        "titleChanged": change.title_changed,
        "contentChanged": change.content_changed,
        "source": "tier1",
    }


class MongoSink:
    """Sink over the notices collection — dedup.py write bodies verbatim.

    The touch buffer is run-level and flat: under run_crawl's
    Semaphore(5), one source's flush may drain touches another source
    buffered mid-page. Every op carries its own articleNo+sourceId filter
    and bulk_write is unordered, so writes always land correctly; the
    drift from the old page-local buffer is failure *attribution* — a
    failing flush can lose a sibling source's drained touches while that
    source still reports success. Flush isolation is a pre-1.0 revisit
    item (adr-006 §⑪).
    """

    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._collection = collection
        self._touches: list[dict[str, Any]] = []
        self._prepared = False

    async def prepare(self, source: SourceSpec) -> None:
        # Indexes are collection-global; N per-source prepares collapse to
        # one ensure_indexes so the op stream matches the old run-level call.
        if self._prepared:
            return
        await ensure_indexes(self._collection)
        self._prepared = True

    async def accept(self, event: CrawlEvent) -> Outcome | None:
        match event:
            case NoticeCrawled(notice=notice, change=None):
                return await self._upsert(notice)
            case NoticeCrawled(notice=notice, change=ChangeInfo() as change):
                await self._update_with_history(notice, _edit_entry(change))
                return Outcome.UPDATED
            case NoticeUnchanged():
                self._touches.append({
                    "articleNo": event.article_no,
                    "sourceId": event.source_id,
                    "views": event.views,
                })
                return None
            case ContentRefreshed(ref=ref, fields=fields):
                await self._collection.update_one(
                    {"articleNo": ref.article_no, "sourceId": event.source_id},
                    {"$set": {
                        **fields,
                        "crawledAt": datetime.now(timezone.utc),
                    }},
                )
                return Outcome.UPDATED
            case _:
                # Tolerant reader: unknown events are silently ignored
                # (adr-006 §⑧; pinned by the sink contract test).
                return None

    async def flush(self) -> None:
        items, self._touches = self._touches, []
        if not items:
            return
        now = datetime.now(timezone.utc)
        ops = [
            {
                "updateOne": {
                    "filter": {"articleNo": item["articleNo"], "sourceId": item["sourceId"]},
                    "update": {"$set": {"views": item["views"], "crawledAt": now}},
                }
            }
            for item in items
        ]
        await self._collection.bulk_write(
            [
                _to_pymongo_op(op) for op in ops
            ],
            ordered=False,
        )

    async def _upsert(self, notice: Notice) -> Outcome:
        doc = asdict(notice)
        edit_history = doc.pop("editHistory", [])
        edit_count = doc.pop("editCount", 0)
        is_deleted = doc.pop("isDeleted", False)
        consecutive_failures = doc.pop("consecutiveFailures", 0)
        result = await self._collection.update_one(
            {"articleNo": notice.articleNo, "sourceId": notice.sourceId},
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
        return Outcome.INSERTED if result.upserted_id is not None else Outcome.UPDATED

    async def _update_with_history(
        self,
        notice: Notice,
        edit_entry: dict[str, Any],
    ) -> None:
        doc = asdict(notice)
        doc.pop("editHistory", None)
        doc.pop("editCount", None)
        doc.pop("isDeleted", None)
        doc.pop("consecutiveFailures", None)
        await self._collection.update_one(
            {"articleNo": notice.articleNo, "sourceId": notice.sourceId},
            {
                "$set": doc,
                "$push": {"editHistory": {"$each": [edit_entry], "$slice": -20}},
                "$inc": {"editCount": 1},
            },
        )
