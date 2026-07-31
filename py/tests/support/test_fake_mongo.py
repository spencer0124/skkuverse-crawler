"""Unit tests for FakeCollection itself.

These test the fake in isolation; tests/conformance/ additionally replays the
same operations against a real MongoDB to pin fidelity.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pymongo import ReturnDocument, UpdateOne
from pymongo.errors import BulkWriteError, DuplicateKeyError

from tests.support.fake_mongo import FakeCollection, FakeDatabase


async def _all_docs(coll: FakeCollection) -> list[dict]:
    return [doc async for doc in coll.find({})]


# ---------------------------------------------------------------------------
# update_one / upsert
# ---------------------------------------------------------------------------


class TestUpdateOne:
    async def test_upsert_inserts_with_filter_seeding_and_upserted_id(self):
        coll = FakeCollection()
        result = await coll.update_one(
            {"articleNo": 1, "sourceId": "skku-main"},
            {"$set": {"title": "t"}, "$setOnInsert": {"editCount": 0}},
            upsert=True,
        )
        assert result.upserted_id is not None
        (doc,) = await _all_docs(coll)
        assert doc["articleNo"] == 1
        assert doc["sourceId"] == "skku-main"
        assert doc["title"] == "t"
        assert doc["editCount"] == 0

    async def test_setoninsert_not_applied_on_update(self):
        coll = FakeCollection()
        await coll.update_one(
            {"articleNo": 1, "sourceId": "s"},
            {"$set": {"title": "a"}, "$setOnInsert": {"editCount": 0}},
            upsert=True,
        )
        result = await coll.update_one(
            {"articleNo": 1, "sourceId": "s"},
            {"$set": {"title": "b"}, "$setOnInsert": {"editCount": 99}},
            upsert=True,
        )
        assert result.upserted_id is None
        (doc,) = await _all_docs(coll)
        assert doc["title"] == "b"
        assert doc["editCount"] == 0

    async def test_no_upsert_no_match_is_noop(self):
        coll = FakeCollection()
        result = await coll.update_one({"articleNo": 9}, {"$set": {"title": "x"}})
        assert result.matched_count == 0
        assert await _all_docs(coll) == []

    async def test_inc_on_missing_field_starts_at_zero(self):
        coll = FakeCollection()
        await coll.update_one({"articleNo": 1}, {"$set": {"a": 1}}, upsert=True)
        await coll.update_one({"articleNo": 1}, {"$inc": {"editCount": 1}})
        (doc,) = await _all_docs(coll)
        assert doc["editCount"] == 1


class TestPushSlice:
    @pytest.mark.parametrize("existing_len", [0, 19, 20, 21])
    async def test_push_each_slice_minus_20(self, existing_len):
        coll = FakeCollection()
        await coll.update_one(
            {"articleNo": 1},
            {"$set": {"editHistory": [{"n": i} for i in range(existing_len)]}},
            upsert=True,
        )
        await coll.update_one(
            {"articleNo": 1},
            {"$push": {"editHistory": {"$each": [{"n": "new"}], "$slice": -20}}},
        )
        (doc,) = await _all_docs(coll)
        history = doc["editHistory"]
        assert len(history) == min(existing_len + 1, 20)
        assert history[-1] == {"n": "new"}

    async def test_push_each_multiple(self):
        coll = FakeCollection()
        await coll.update_one({"articleNo": 1}, {"$set": {"h": []}}, upsert=True)
        await coll.update_one(
            {"articleNo": 1}, {"$push": {"h": {"$each": [1, 2, 3], "$slice": -20}}}
        )
        (doc,) = await _all_docs(coll)
        assert doc["h"] == [1, 2, 3]


# ---------------------------------------------------------------------------
# unique index / bulk_write
# ---------------------------------------------------------------------------


class TestUniqueIndex:
    async def test_duplicate_upsert_insert_raises(self):
        coll = FakeCollection()
        await coll.create_index([("articleNo", 1), ("sourceId", 1)], unique=True)
        await coll.update_one(
            {"articleNo": 1, "sourceId": "s"}, {"$set": {"t": "a"}}, upsert=True
        )
        # Same unique key via a DIFFERENT filter → insert path → duplicate.
        with pytest.raises(DuplicateKeyError):
            await coll.update_one(
                {"articleNo": 1, "sourceId": "s", "extra": "x"},
                {"$set": {"t": "b"}},
                upsert=True,
            )


class TestBulkWrite:
    async def test_unordered_continues_past_duplicate_key(self):
        coll = FakeCollection()
        await coll.create_index([("articleNo", 1), ("sourceId", 1)], unique=True)
        await coll.update_one(
            {"articleNo": 1, "sourceId": "s"}, {"$set": {"t": "a"}}, upsert=True
        )
        ops = [
            UpdateOne({"articleNo": 1, "sourceId": "s", "x": 1}, {"$set": {"t": "dup"}}, upsert=True),
            UpdateOne({"articleNo": 2, "sourceId": "s"}, {"$set": {"t": "b"}}, upsert=True),
        ]
        with pytest.raises(BulkWriteError):
            await coll.bulk_write(ops, ordered=False)
        docs = await _all_docs(coll)
        assert {d["articleNo"] for d in docs} == {1, 2}  # op after the failure applied

    async def test_recorded_as_single_ops_entry(self):
        coll = FakeCollection()
        await coll.bulk_write(
            [UpdateOne({"articleNo": 1}, {"$set": {"views": 5}})], ordered=False
        )
        bulk_entries = [op for op in coll.ops if op[0] == "bulk_write"]
        assert len(bulk_entries) == 1
        assert bulk_entries[0][1]["ops"] == [
            {"filter": {"articleNo": 1}, "update": {"$set": {"views": 5}}, "upsert": False}
        ]

    async def test_ordered_true_not_implemented(self):
        coll = FakeCollection()
        with pytest.raises(NotImplementedError):
            await coll.bulk_write([UpdateOne({}, {"$set": {"a": 1}})], ordered=True)


# ---------------------------------------------------------------------------
# find / filters / cursor
# ---------------------------------------------------------------------------


class TestFind:
    async def _seed(self, coll: FakeCollection) -> None:
        for n, doc in enumerate(
            [
                {"sourceId": "a", "content": None, "date": "2026-03-10"},
                {"sourceId": "a", "content": "x", "date": "2026-04-01"},
                {"sourceId": "b", "content": "", "date": "2026-05-01", "isDeleted": True},
            ]
        ):
            await coll.update_one({"articleNo": n}, {"$set": doc}, upsert=True)

    async def test_in_and_projection(self):
        coll = FakeCollection()
        await self._seed(coll)
        docs = [
            d
            async for d in coll.find(
                {"articleNo": {"$in": [0, 2]}}, {"articleNo": 1, "date": 1}
            )
        ]
        assert [d["articleNo"] for d in docs] == [0, 2]
        assert all(set(d) == {"articleNo", "date", "_id"} for d in docs)

    async def test_or_null_matches_none_and_empty(self):
        coll = FakeCollection()
        await self._seed(coll)
        docs = [
            d async for d in coll.find({"$or": [{"content": None}, {"content": ""}]})
        ]
        assert {d["articleNo"] for d in docs} == {0, 2}

    async def test_null_equality_matches_missing_field(self):
        coll = FakeCollection()
        await coll.update_one({"articleNo": 1}, {"$set": {"title": "t"}}, upsert=True)
        docs = [d async for d in coll.find({"content": None})]
        assert len(docs) == 1

    async def test_ne_true_matches_missing_field(self):
        coll = FakeCollection()
        await self._seed(coll)
        docs = [d async for d in coll.find({"isDeleted": {"$ne": True}})]
        assert {d["articleNo"] for d in docs} == {0, 1}

    async def test_not_gte_matches_missing_field(self):
        coll = FakeCollection()
        await coll.update_one({"articleNo": 1}, {"$set": {"fails": 5}}, upsert=True)
        await coll.update_one({"articleNo": 2}, {"$set": {"fails": 1}}, upsert=True)
        await coll.update_one({"articleNo": 3}, {"$set": {"t": "x"}}, upsert=True)
        docs = [d async for d in coll.find({"fails": {"$not": {"$gte": 3}}})]
        assert {d["articleNo"] for d in docs} == {2, 3}

    async def test_exists_gte_nin(self):
        coll = FakeCollection()
        await self._seed(coll)
        assert len([d async for d in coll.find({"isDeleted": {"$exists": True}})]) == 1
        assert len([d async for d in coll.find({"date": {"$gte": "2026-04-01"}})]) == 2
        assert len([d async for d in coll.find({"sourceId": {"$nin": ["a"]}})]) == 1

    async def test_sort_and_limit(self):
        coll = FakeCollection()
        await self._seed(coll)
        docs = [d async for d in coll.find({}).sort("date", -1).limit(2)]
        assert [d["date"] for d in docs] == ["2026-05-01", "2026-04-01"]

    async def test_count_documents(self):
        coll = FakeCollection()
        await self._seed(coll)
        assert await coll.count_documents({"sourceId": "a"}) == 2

    async def test_cursor_docs_are_copies(self):
        coll = FakeCollection()
        await self._seed(coll)
        (doc,) = [d async for d in coll.find({"articleNo": 1})]
        doc["content"] = "MUTATED"
        (again,) = [d async for d in coll.find({"articleNo": 1})]
        assert again["content"] == "x"


# ---------------------------------------------------------------------------
# find_one_and_update / datetime truncation / honesty pins
# ---------------------------------------------------------------------------


class TestFindOneAndUpdate:
    async def test_return_before_and_after(self):
        coll = FakeCollection()
        await coll.update_one({"articleNo": 1}, {"$set": {"views": 1}}, upsert=True)
        before = await coll.find_one_and_update(
            {"articleNo": 1}, {"$set": {"views": 2}}, return_document=ReturnDocument.BEFORE
        )
        assert before["views"] == 1
        after = await coll.find_one_and_update(
            {"articleNo": 1}, {"$set": {"views": 3}}, return_document=ReturnDocument.AFTER
        )
        assert after["views"] == 3

    async def test_no_match_returns_none(self):
        coll = FakeCollection()
        assert await coll.find_one_and_update({"articleNo": 9}, {"$set": {"a": 1}}) is None


class TestBsonFidelity:
    async def test_datetime_truncated_to_ms(self):
        coll = FakeCollection()
        stamp = datetime(2026, 7, 31, 12, 0, 0, 123456, tzinfo=timezone.utc)
        await coll.update_one({"articleNo": 1}, {"$set": {"crawledAt": stamp}}, upsert=True)
        (doc,) = await _all_docs(coll)
        assert doc["crawledAt"].microsecond == 123000


class TestHonestyPins:
    """Unsupported operations must raise, never silently no-op."""

    async def test_aggregation_pipeline_update_raises(self):
        coll = FakeCollection()
        await coll.update_one({"articleNo": 1}, {"$set": {"views": 1}}, upsert=True)
        with pytest.raises(NotImplementedError):
            await coll.find_one_and_update(
                {"articleNo": 1}, [{"$set": {"views": {"$add": [1, 1]}}}]
            )

    async def test_expr_filter_raises(self):
        coll = FakeCollection()
        with pytest.raises(NotImplementedError):
            [d async for d in coll.find({"$expr": {"$ne": ["$a", "$b"]}})]

    async def test_unknown_update_operator_raises(self):
        coll = FakeCollection()
        await coll.update_one({"articleNo": 1}, {"$set": {"a": 1}}, upsert=True)
        with pytest.raises(NotImplementedError):
            await coll.update_one({"articleNo": 1}, {"$unset": {"a": ""}})

    async def test_unknown_query_operator_raises(self):
        coll = FakeCollection()
        await coll.update_one({"articleNo": 1}, {"$set": {"a": 1}}, upsert=True)
        with pytest.raises(NotImplementedError):
            [d async for d in coll.find({"a": {"$lt": 5}})]


class TestFakeDatabase:
    def test_getitem_returns_same_collection(self):
        db = FakeDatabase()
        assert db["notices"] is db["notices"]
        assert db["notices"].name == "notices"
