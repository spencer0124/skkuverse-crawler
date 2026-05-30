from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from skkuverse_crawler.schedule.repository import upsert_year

YEAR_DOC = {
    "_id": 2026,
    "academicYear": 2026,
    "events": [{"month": 8, "startDate": "2026-08-10", "endDate": None, "content": "x"}],
    "eventCount": 1,
    "yearHash": "newhash",
    "sourceUrl": "http://example/2026",
}


async def test_upsert_skips_when_hash_unchanged(mock_collection):
    mock_collection.find_one = AsyncMock(return_value={"yearHash": "newhash"})
    mock_collection.update_one = AsyncMock()

    result = await upsert_year(mock_collection, YEAR_DOC)

    assert result == "skipped"
    mock_collection.update_one.assert_not_awaited()


async def test_upsert_updates_when_hash_changed(mock_collection):
    mock_collection.find_one = AsyncMock(return_value={"yearHash": "oldhash"})
    mock_collection.update_one = AsyncMock(
        return_value=SimpleNamespace(upserted_id=None)
    )

    result = await upsert_year(mock_collection, YEAR_DOC)

    assert result == "updated"
    mock_collection.update_one.assert_awaited_once()
    args, kwargs = mock_collection.update_one.call_args
    assert args[0] == {"_id": 2026}
    assert kwargs["upsert"] is True
    # _id must not leak into the $set payload
    assert "_id" not in args[1]["$set"]
    assert args[1]["$set"]["yearHash"] == "newhash"


async def test_upsert_inserts_when_absent(mock_collection):
    mock_collection.find_one = AsyncMock(return_value=None)
    mock_collection.update_one = AsyncMock(
        return_value=SimpleNamespace(upserted_id=2026)
    )

    result = await upsert_year(mock_collection, YEAR_DOC)

    assert result == "inserted"
