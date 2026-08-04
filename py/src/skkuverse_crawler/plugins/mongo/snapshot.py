"""Storage for the second archetype: whole documents, keyed naturally.

`MongoSink` stores the notices shape — many rows per source, identified by
`articleNo` + `sourceId`, with edit history and a views touch buffer. That
is one way to be a crawl, not the only one. Bus timetables, cafeteria
menus and an academic calendar are all the other shape: **one document per
key, replaced wholesale**, where the key is `"hssc"` or a date or a year
rather than an article number, and there is no pagination and nothing to
diff per item.

This sink is that shape and nothing more. It is deliberately small — if it
grows a second responsibility, that is a sign the module should be
emitting different events instead.

What it reads off the item, by duck typing rather than a Protocol (see
core/events.ItemCrawled for why there is no CrawlItem):

    .key    -> str            the document _id
    .fields -> Mapping        merged into $set verbatim

`_updatedAt` is added by this sink, because when a write happened is
storage's own knowledge — the same reason MongoSink stamps `crawledAt`.
Anything the *module* knows about freshness (when the upstream fetch
actually happened, whether the upstream was healthy) belongs in `fields`,
where the module can name it.

No change detection here on purpose. Deciding an item is unchanged needs
the previous state, which is what `SeenIndex` and `ItemUnchanged` are for;
a sink that silently skipped a write would also have to lie to the runner,
which reads `None` as INSERTED. A module with a hash compares it and emits
`ItemUnchanged`, exactly as notices does.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection

from ...core.events import CrawlEvent, ItemCrawled
from ...core.ports import Outcome, SourceSpec


class SnapshotSink:
    """Upsert whole documents by natural key.

    No indexes to ensure: the key IS `_id`, which Mongo indexes uniquely
    on its own. `prepare` and `flush` are therefore genuinely empty rather
    than accidentally so — every write lands immediately, so there is no
    buffer that a missed flush could strand.
    """

    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._collection = collection

    async def prepare(self, source: SourceSpec) -> None:
        return None

    async def accept(self, event: CrawlEvent) -> Outcome | None:
        match event:
            case ItemCrawled(item=snapshot):
                return await self._store(snapshot)
            case _:
                # Tolerant reader (adr-006 §⑧): the progress tier and
                # anything a later release adds are not this sink's
                # business.
                return None

    async def flush(self) -> None:
        return None

    async def _store(self, snapshot: Any) -> Outcome:
        key, fields = _unpack(snapshot)
        result = await self._collection.update_one(
            {"_id": key},
            {"$set": {**fields, "_updatedAt": datetime.now(timezone.utc)}},
            upsert=True,
        )
        return Outcome.INSERTED if result.upserted_id is not None else Outcome.UPDATED


def _unpack(snapshot: Any) -> tuple[str, dict[str, Any]]:
    """Read the two attributes this sink needs, and say so if they are absent.

    The payload is untyped by design, so a module handing over the wrong
    object gets a message naming what was expected instead of an
    AttributeError from inside a Mongo call. An empty key is refused for
    the same reason `_id: ""` is a real document nobody meant to write.
    """
    missing = [name for name in ("key", "fields") if not hasattr(snapshot, name)]
    if missing:
        raise TypeError(
            f"SnapshotSink needs an item with .key and .fields, but "
            f"{type(snapshot).__name__} has no {', '.join(missing)}"
        )
    key = snapshot.key
    if not isinstance(key, str) or not key:
        raise TypeError(
            f"SnapshotSink needs a non-empty str key, got {key!r} "
            f"from {type(snapshot).__name__}"
        )
    return key, dict(snapshot.fields)
