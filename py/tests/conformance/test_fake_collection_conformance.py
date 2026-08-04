"""Level-1 conformance: FakeCollection vs real MongoDB, operator by operator.

The whole PR ladder trusts the goldens, and the goldens trust the fake.
Each case here runs the SAME operation sequence against both backends and
compares (exception type, return value, final collection state). A fidelity
bug in the fake shows up as a diff between the two columns.

Known asymmetry (documented in fake_mongo's docstring): ``.ops`` is a
fake-only artifact — real Mongo does not expose round trips, so level 1
verifies *state*, and ``.ops`` stays a fake-only counting device.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import pytest
from pymongo import ReturnDocument, UpdateOne

from tests.support.fake_mongo import FakeCollection
from tests.support.normalize import normalize_bson, sort_docs

pytestmark = pytest.mark.mongo

_UNIQUE_KEYS = [("articleNo", 1), ("sourceId", 1)]


def _fixed_dt(microsecond: int = 123456) -> datetime:
    return datetime(2026, 7, 1, 3, 4, 5, microsecond, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Scenarios — backend-agnostic coroutines; deterministic (fixed datetimes)
# ---------------------------------------------------------------------------


def _push_slice_case(existing_len: int) -> Callable:
    async def run(coll: Any) -> Any:
        await coll.update_one(
            {"articleNo": 1, "sourceId": "s"},
            {"$set": {"editHistory": [{"n": i} for i in range(existing_len)]}},
            upsert=True,
        )
        await coll.update_one(
            {"articleNo": 1, "sourceId": "s"},
            {"$push": {"editHistory": {"$each": [{"n": "new"}], "$slice": -20}}},
        )
        return None

    return run


async def _push_each_multi(coll: Any) -> Any:
    await coll.update_one(
        {"articleNo": 1, "sourceId": "s"}, {"$set": {"h": [0]}}, upsert=True
    )
    await coll.update_one(
        {"articleNo": 1, "sourceId": "s"},
        {"$push": {"h": {"$each": [1, 2, 3], "$slice": -20}}},
    )
    return None


async def _bulk_unordered_continues_past_dup(coll: Any) -> Any:
    await coll.create_index(_UNIQUE_KEYS, unique=True)
    await coll.update_one(
        {"articleNo": 1, "sourceId": "s"}, {"$set": {"t": "a"}}, upsert=True
    )
    await coll.bulk_write(
        [
            # Insert path that collides with the unique key above...
            UpdateOne(
                {"articleNo": 1, "sourceId": "s", "extra": "x"},
                {"$set": {"t": "dup"}},
                upsert=True,
            ),
            # ...and an op AFTER the failure that must still apply.
            UpdateOne({"articleNo": 2, "sourceId": "s"}, {"$set": {"t": "b"}}, upsert=True),
        ],
        ordered=False,
    )
    return None


async def _find_one_and_update_returns(coll: Any) -> Any:
    await coll.update_one(
        {"articleNo": 1, "sourceId": "s"}, {"$set": {"views": 1}}, upsert=True
    )
    before = await coll.find_one_and_update(
        {"articleNo": 1, "sourceId": "s"},
        {"$set": {"views": 2}},
        return_document=ReturnDocument.BEFORE,
    )
    after = await coll.find_one_and_update(
        {"articleNo": 1, "sourceId": "s"},
        {"$set": {"views": 3}},
        return_document=ReturnDocument.AFTER,
    )
    missing = await coll.find_one_and_update(
        {"articleNo": 99, "sourceId": "s"}, {"$set": {"views": 0}}
    )
    return normalize_bson([before, after, missing])


async def _upsert_semantics(coll: Any) -> Any:
    inserted = await coll.update_one(
        {"articleNo": 1, "sourceId": "s"},
        {"$set": {"title": "a"}, "$setOnInsert": {"editCount": 0}},
        upsert=True,
    )
    updated = await coll.update_one(
        {"articleNo": 1, "sourceId": "s"},
        {"$set": {"title": "b"}, "$setOnInsert": {"editCount": 99}},
        upsert=True,
    )
    return {
        "insert_has_upserted_id": inserted.upserted_id is not None,
        "update_has_upserted_id": updated.upserted_id is not None,
        "update_matched": updated.matched_count,
    }


async def _upsert_by_explicit_id(coll: Any) -> Any:
    """The snapshot archetype's addressing: the key IS _id.

    Mongo generates an _id only when the filter did not pin one, so the
    second call must MATCH rather than insert again. The fake used to
    overwrite the filter's _id with a fresh ObjectId, which made every
    write of the same key report inserted forever and left one orphan
    document per tick — invisible in unit tests, ruinous for a 10-second
    poller.
    """
    first = await coll.update_one(
        {"_id": "hssc"}, {"$set": {"data": [1], "_updatedAt": _fixed_dt()}}, upsert=True
    )
    second = await coll.update_one(
        {"_id": "hssc"}, {"$set": {"data": [1, 2], "_updatedAt": _fixed_dt()}}, upsert=True
    )
    return {
        "first_upserted_id": first.upserted_id,
        "second_has_upserted_id": second.upserted_id is not None,
        "second_matched": second.matched_count,
    }


async def _unique_violation(coll: Any) -> Any:
    await coll.create_index(_UNIQUE_KEYS, unique=True)
    await coll.update_one(
        {"articleNo": 1, "sourceId": "s"}, {"$set": {"t": "a"}}, upsert=True
    )
    await coll.update_one(
        {"articleNo": 1, "sourceId": "s", "extra": "x"}, {"$set": {"t": "b"}}, upsert=True
    )
    return None


async def _seed_filter_docs(coll: Any) -> None:
    for article_no, fields in [
        (1, {"sourceId": "a", "content": None, "date": "2026-03-10", "fails": 5}),
        (2, {"sourceId": "a", "content": "x", "date": "2026-04-01", "fails": 1}),
        (3, {"sourceId": "b", "content": "", "date": "2026-05-01", "isDeleted": True}),
        (4, {"sourceId": "c", "title": "missing-fields", "date": "2026-06-01"}),
    ]:
        await coll.update_one({"articleNo": article_no}, {"$set": fields}, upsert=True)


async def _find_filters(coll: Any) -> Any:
    """The exact filter shapes src/ uses, incl. Mongo missing-field semantics."""
    await _seed_filter_docs(coll)
    unordered_queries = [
        coll.find({"articleNo": {"$in": [1, 3]}}, {"articleNo": 1, "date": 1}),
        coll.find({"$or": [{"content": None}, {"content": ""}]}),  # find_null_content
        coll.find({"isDeleted": {"$ne": True}}),  # update_checker window
        coll.find({"fails": {"$not": {"$gte": 3}}}),  # summary retry cap
        coll.find({"fails": {"$exists": True}}),
        coll.find({"date": {"$gte": "2026-04-01"}}),
        coll.find({"sourceId": {"$nin": ["a"]}}),
    ]
    results = []
    for cursor in unordered_queries:
        results.append(sort_docs(normalize_bson([doc async for doc in cursor])))
    ordered = coll.find({}).sort("date", -1).limit(2)
    results.append(normalize_bson([doc async for doc in ordered]))
    results.append(await coll.count_documents({"sourceId": "a"}))
    return results


async def _datetime_ms_truncation(coll: Any) -> Any:
    await coll.update_one(
        {"articleNo": 1, "sourceId": "s"},
        {"$set": {"crawledAt": _fixed_dt(123456)}},
        upsert=True,
    )
    return None


def _soft_delete_counter(seed: dict[str, Any]) -> Callable:
    """update_checker's 404 counter, verbatim.

    The two $set stages are sequential: stage 2's $consecutiveFailures is
    the value stage 1 just wrote. That is what makes the third failure —
    not the fourth — cross the threshold, so it is exactly the semantic
    the fake must not get wrong.
    """

    async def run(coll: Any) -> Any:
        await coll.update_one(
            {"articleNo": 1, "sourceId": "s"}, {"$set": {"title": "t", **seed}}, upsert=True
        )
        updated = await coll.find_one_and_update(
            {"articleNo": 1, "sourceId": "s"},
            [
                {"$set": {
                    "consecutiveFailures": {
                        "$add": [{"$ifNull": ["$consecutiveFailures", 0]}, 1]
                    },
                }},
                {"$set": {
                    "isDeleted": {
                        "$cond": {
                            "if": {"$gte": ["$consecutiveFailures", 3]},
                            "then": True,
                            "else": {"$ifNull": ["$isDeleted", False]},
                        }
                    },
                }},
            ],
            return_document=ReturnDocument.AFTER,
        )
        return normalize_bson([updated])

    return run


async def _dotted_path_into_array(coll: Any) -> Any:
    """`editHistory.source` — the repair scan's query.

    Mongo fans a dotted path out over array elements and matches when ANY
    of them matches, which is what makes this mean "has a tier2 entry".
    The fake had to grow that; getting it subtly wrong would make the
    repair walk the wrong population, so it is checked against the real
    thing rather than reasoned about.
    """
    await coll.update_one(
        {"articleNo": 1, "sourceId": "d"},
        {"$set": {"articleNo": 1, "sourceId": "d",
                  "editHistory": [{"source": "tier1"}, {"source": "tier2"}]}},
        upsert=True,
    )
    await coll.update_one(
        {"articleNo": 2, "sourceId": "d"},
        {"$set": {"articleNo": 2, "sourceId": "d",
                  "editHistory": [{"source": "tier1"}]}},
        upsert=True,
    )
    await coll.update_one(
        {"articleNo": 3, "sourceId": "d"},
        {"$set": {"articleNo": 3, "sourceId": "d", "editHistory": []}},
        upsert=True,
    )
    # No editHistory field at all — the case a naive implementation
    # crashes on rather than skipping.
    await coll.update_one(
        {"articleNo": 4, "sourceId": "d"},
        {"$set": {"articleNo": 4, "sourceId": "d"}},
        upsert=True,
    )
    found = [doc async for doc in coll.find({"editHistory.source": "tier2"}, {"articleNo": 1})]
    absent = [doc async for doc in coll.find({"editHistory.source": "nope"}, {"articleNo": 1})]
    return sort_docs(normalize_bson(found)), sort_docs(normalize_bson(absent))


@dataclass(frozen=True)
class Case:
    name: str
    run: Callable
    expect_error: str | None = None


CASES = [
    Case("push_slice_len0", _push_slice_case(0)),
    Case("push_slice_len19", _push_slice_case(19)),
    Case("push_slice_len20", _push_slice_case(20)),
    Case("push_slice_len21", _push_slice_case(21)),
    Case("push_each_multi", _push_each_multi),
    Case("bulk_unordered_continues_past_dup", _bulk_unordered_continues_past_dup, "BulkWriteError"),
    Case("find_one_and_update_returns", _find_one_and_update_returns),
    Case("upsert_semantics", _upsert_semantics),
    Case("upsert_by_explicit_id", _upsert_by_explicit_id),
    Case("unique_violation", _unique_violation, "DuplicateKeyError"),
    Case("find_filters", _find_filters),
    Case("dotted_path_into_array", _dotted_path_into_array),
    Case("datetime_ms_truncation", _datetime_ms_truncation),
    # Pipeline updates: the counter matrix, including the missing-field
    # cases $ifNull exists for.
    Case("pipeline_counter_absent_fields", _soft_delete_counter({})),
    Case("pipeline_counter_from_zero", _soft_delete_counter({"consecutiveFailures": 0})),
    Case("pipeline_counter_below_threshold", _soft_delete_counter({"consecutiveFailures": 1})),
    Case("pipeline_counter_crosses_threshold", _soft_delete_counter({"consecutiveFailures": 2})),
    Case("pipeline_counter_past_threshold", _soft_delete_counter({"consecutiveFailures": 5})),
    Case(
        "pipeline_counter_preserves_existing_delete_flag",
        _soft_delete_counter({"consecutiveFailures": 0, "isDeleted": True}),
    ),
]


async def _execute(coll: Any, case: Case) -> tuple[Any, str | None]:
    try:
        return await case.run(coll), None
    except Exception as exc:  # noqa: BLE001 — exception type IS the assertion
        return None, type(exc).__name__


async def _dump(coll: Any) -> Any:
    return sort_docs(normalize_bson([doc async for doc in coll.find({})]))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
async def test_fake_matches_real(case: Case, real_collection):
    fake = FakeCollection()
    fake_ret, fake_err = await _execute(fake, case)
    real_ret, real_err = await _execute(real_collection, case)

    assert fake_err == real_err == case.expect_error
    assert fake_ret == real_ret
    assert await _dump(fake) == await _dump(real_collection)
