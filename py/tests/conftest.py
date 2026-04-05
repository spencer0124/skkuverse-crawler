from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from skkuverse_crawler.shared import bus_cache


@pytest.fixture()
def mock_collection():
    """A mock MongoDB collection with async methods."""
    coll = AsyncMock()
    coll.update_one = AsyncMock()
    coll.find_one = AsyncMock(return_value=None)
    coll.create_index = AsyncMock()
    return coll


@pytest.fixture(autouse=True)
def _mock_db(mock_collection):
    """Prevent real MongoDB connections in all tests.

    Patches get_db everywhere it's imported so no real Mongo calls happen.
    """
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)

    async def fake_get_db():
        return mock_db

    # Patch in every module that imports get_db
    with (
        patch("skkuverse_crawler.shared.db.get_db", side_effect=fake_get_db),
        patch("skkuverse_crawler.shared.bus_cache.get_db", side_effect=fake_get_db),
    ):
        # Also reset bus_cache index flag
        bus_cache._index_ensured = False
        yield mock_collection
        bus_cache._index_ensured = False
