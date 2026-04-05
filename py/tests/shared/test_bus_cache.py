from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from skkuverse_crawler.shared import bus_cache


async def test_ensure_index_creates_ttl_index(mock_collection):
    await bus_cache.ensure_index()

    mock_collection.create_index.assert_awaited_once_with(
        "_updatedAt", expireAfterSeconds=60, name="ttl_updatedAt"
    )


async def test_ensure_index_only_runs_once(mock_collection):
    await bus_cache.ensure_index()
    await bus_cache.ensure_index()
    await bus_cache.ensure_index()

    assert mock_collection.create_index.await_count == 1


async def test_write_upserts_with_utc_timestamp(mock_collection):
    await bus_cache.write("hssc", [{"bus": 1}])

    mock_collection.update_one.assert_awaited_once()
    call_args = mock_collection.update_one.call_args
    assert call_args[0][0] == {"_id": "hssc"}

    set_doc = call_args[0][1]["$set"]
    assert set_doc["data"] == [{"bus": 1}]
    assert isinstance(set_doc["_updatedAt"], datetime)
    assert set_doc["_updatedAt"].tzinfo == timezone.utc

    assert call_args[1]["upsert"] is True


async def test_read_returns_data_when_found(mock_collection):
    mock_collection.find_one = AsyncMock(
        return_value={"_id": "hssc", "data": [{"a": 1}]}
    )

    result = await bus_cache.read("hssc")
    assert result == [{"a": 1}]


async def test_read_returns_none_when_not_found(mock_collection):
    mock_collection.find_one = AsyncMock(return_value=None)

    result = await bus_cache.read("missing_key")
    assert result is None
