"""SnapshotSink — the exact op a snapshot-shaped module produces.

This is the parity gate for moving bus out of skkuverse-server, and it
exists before any fetching does. The server writes `bus_cache` documents
shaped `{_id, data, _updatedAt}` and its API reads them directly, so if
the crawler's op differs the app breaks in a way no crawler test would
notice. Pinning the op here means the fetcher work in a later phase only
has to get the *payload* right.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest

from skkuverse_crawler.core.events import (
    BatchCompleted,
    ItemCrawled,
    ItemUnchanged,
    SourceFinished,
    SourceStarted,
)
from skkuverse_crawler.core.ports import Outcome, SourceSpec
from skkuverse_crawler.core.testing import assert_sink_contract
from skkuverse_crawler.plugins.mongo.snapshot import SnapshotSink
from tests.support.fake_mongo import FakeCollection


@dataclass(frozen=True)
class _Snapshot:
    """What a snapshot module hands over. Deliberately defined in the test,
    not imported: the sink duck-types two attributes rather than owning a
    shared payload class, which is what keeps `modules/` from importing
    `plugins/`."""

    key: str
    fields: dict[str, Any] = field(default_factory=dict)


FETCHED_AT = datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc)


def _bus_like() -> _Snapshot:
    return _Snapshot(
        key="hssc",
        fields={"data": [{"stop": "율전"}], "fetchedAt": FETCHED_AT, "sourceOk": True},
    )


class TestTheOpItProduces:
    async def test_it_upserts_by_id_with_the_module_fields_merged(self):
        collection = FakeCollection()
        await SnapshotSink(collection).accept(
            ItemCrawled(source_id="bus-hssc", item=_bus_like())
        )

        assert len(collection.ops) == 1
        name, args = collection.ops[0]
        assert name == "update_one"
        assert args["filter"] == {"_id": "hssc"}
        assert args["upsert"] is True

        update = args["update"]
        assert set(update) == {"$set"}, "no $setOnInsert, no $push — replace is the shape"
        assert update["$set"]["data"] == [{"stop": "율전"}]
        assert update["$set"]["fetchedAt"] == FETCHED_AT
        assert update["$set"]["sourceOk"] is True

    async def test_updatedAt_is_stamped_by_the_sink(self):
        """When the write happened is storage's knowledge, the same way
        MongoSink stamps crawledAt. When the *fetch* happened is the
        module's, and rides in fields."""
        collection = FakeCollection()
        before = datetime.now(timezone.utc)
        await SnapshotSink(collection).accept(
            ItemCrawled(source_id="bus-hssc", item=_bus_like())
        )
        stamped = collection.ops[0][1]["update"]["$set"]["_updatedAt"]
        assert before <= stamped <= datetime.now(timezone.utc)
        assert stamped != FETCHED_AT

    async def test_one_write_per_item_with_nothing_buffered(self):
        """flush is empty because there is no buffer — a dropped flush
        cannot strand a snapshot the way it can strand a touch."""
        collection = FakeCollection()
        sink = SnapshotSink(collection)
        await sink.accept(ItemCrawled(source_id="s", item=_Snapshot(key="a")))
        await sink.accept(ItemCrawled(source_id="s", item=_Snapshot(key="b")))
        assert [op[1]["filter"]["_id"] for op in collection.ops] == ["a", "b"]
        await sink.flush()
        assert len(collection.ops) == 2

    async def test_prepare_creates_no_indexes(self):
        """_id is indexed by Mongo already; ensure_indexes here would be
        two round trips per source for nothing."""
        collection = FakeCollection()
        await SnapshotSink(collection).prepare(SourceSpec(source_id="bus-hssc"))
        assert collection.ops == []


class TestOutcome:
    async def test_first_write_reports_inserted(self):
        collection = FakeCollection()
        outcome = await SnapshotSink(collection).accept(
            ItemCrawled(source_id="s", item=_bus_like())
        )
        assert outcome is Outcome.INSERTED

    async def test_rewriting_the_same_key_reports_updated(self):
        """A 10-second poller rewrites the same handful of keys forever, so
        this is the steady state, not the edge case."""
        collection = FakeCollection()
        sink = SnapshotSink(collection)
        await sink.accept(ItemCrawled(source_id="s", item=_bus_like()))
        outcome = await sink.accept(ItemCrawled(source_id="s", item=_bus_like()))
        assert outcome is Outcome.UPDATED


class TestTolerantReader:
    @pytest.mark.parametrize(
        "event",
        [
            SourceStarted(source_id="s", source_name="s"),
            BatchCompleted(source_id="s", index=0),
            ItemUnchanged(source_id="s", article_no=1),
            SourceFinished(source_id="s", stopped_by="done", source_down=False, last_error=""),
        ],
    )
    async def test_events_it_does_not_handle_write_nothing(self, event):
        collection = FakeCollection()
        assert await SnapshotSink(collection).accept(event) is None
        assert collection.ops == []


class TestBadPayloadsFailLoudly:
    """The payload is untyped by design, so the sink is where a wrong
    object has to be caught — otherwise it surfaces as an AttributeError
    from inside a Mongo call, or worse, writes to a key nobody meant."""

    async def test_an_item_without_the_attributes_names_them(self):
        class _Wrong:
            pass

        with pytest.raises(TypeError, match=r"\.key and \.fields"):
            await SnapshotSink(FakeCollection()).accept(
                ItemCrawled(source_id="s", item=_Wrong())
            )

    async def test_a_partially_shaped_item_names_only_what_is_missing(self):
        class _HalfRight:
            key = "k"

        with pytest.raises(TypeError, match="has no fields"):
            await SnapshotSink(FakeCollection()).accept(
                ItemCrawled(source_id="s", item=_HalfRight())
            )

    @pytest.mark.parametrize("bad_key", ["", None, 42])
    async def test_an_unusable_key_is_refused(self, bad_key):
        """`_id: ""` is a perfectly storable document, and `_id: 42` a
        different one from `_id: "42"`. Neither is what a module meant."""
        with pytest.raises(TypeError, match="non-empty str key"):
            await SnapshotSink(FakeCollection()).accept(
                ItemCrawled(source_id="s", item=_Snapshot(key=bad_key))
            )

    async def test_nothing_is_written_when_the_payload_is_refused(self):
        collection = FakeCollection()
        with pytest.raises(TypeError):
            await SnapshotSink(collection).accept(
                ItemCrawled(source_id="s", item=_Snapshot(key=""))
            )
        assert collection.ops == []


class TestFieldIsolation:
    async def test_the_module_mapping_is_copied_not_aliased(self):
        """A snapshot module holds state across ticks; if the sink kept a
        reference, next tick's mutation would rewrite what was already
        sent."""
        collection = FakeCollection()
        fields = {"data": "v1"}
        await SnapshotSink(collection).accept(
            ItemCrawled(source_id="s", item=_Snapshot(key="k", fields=fields))
        )
        fields["data"] = "v2"
        assert collection.ops[0][1]["update"]["$set"]["data"] == "v1"


async def test_it_satisfies_the_shipped_sink_contract():
    await assert_sink_contract(
        SnapshotSink(FakeCollection()),
        sample=ItemCrawled(source_id="__contract_test__", item=_bus_like()),
        sample_article_no=1,
    )
