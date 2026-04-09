from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from skkuverse_crawler.shared import bus_cache
from skkuverse_crawler.shared.config import reset_config


@pytest.fixture(autouse=True)
def _test_env_and_config(monkeypatch):
    """Reset config singleton and set test environment.

    Runs before all other autouse fixtures to ensure config reads
    see CRAWLER_ENV=test.
    """
    reset_config()
    monkeypatch.setenv("CRAWLER_ENV", "test")
    yield
    reset_config()


@pytest.fixture()
def mock_collection():
    """A mock MongoDB collection with async methods."""
    coll = AsyncMock()
    coll.update_one = AsyncMock()
    coll.find_one = AsyncMock(return_value=None)
    coll.create_index = AsyncMock()
    return coll


@pytest.fixture(autouse=True)
def _mock_db(_test_env_and_config, mock_collection):
    """Prevent real MongoDB connections in all tests.

    Depends on _test_env_and_config to guarantee config is
    initialized before any db module import reads it.
    """
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)

    async def fake_get_db():
        return mock_db

    with (
        patch("skkuverse_crawler.shared.db.get_db", side_effect=fake_get_db),
        patch("skkuverse_crawler.shared.bus_cache.get_db", side_effect=fake_get_db),
    ):
        bus_cache._index_ensured = False
        yield mock_collection
        bus_cache._index_ensured = False
