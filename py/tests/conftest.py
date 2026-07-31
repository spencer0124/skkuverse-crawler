from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


@pytest.fixture(autouse=True)
def _no_real_mongo(request, monkeypatch):
    """Make any real MongoDB connection attempt a loud test failure.

    The old `_mock_db` autouse fixture patched `shared.db.get_db`, but most
    consumers bind `get_db` at import time, so the patch never reached them —
    a leaked connection surfaced as a 30s timeout instead of a red test.
    Tests that need a DB opt in via `mock_db_patch` (AsyncMock-based) or the
    characterization harness. Tests marked `@pytest.mark.mongo` talk to a
    real MongoDB (testcontainers) and are exempt.
    """
    if request.node.get_closest_marker("mongo"):
        yield
        return

    from motor.motor_asyncio import AsyncIOMotorClient

    def _refuse_connection(self, *args, **kwargs):
        raise AssertionError(
            "real MongoDB connection attempted in a test — "
            "use the mock_db_patch fixture or mark the test with @pytest.mark.mongo"
        )

    monkeypatch.setattr(AsyncIOMotorClient, "__init__", _refuse_connection)
    yield


@pytest.fixture()
def mock_collection():
    """A mock MongoDB collection with async methods."""
    coll = AsyncMock()
    coll.update_one = AsyncMock()
    coll.find_one = AsyncMock(return_value=None)
    coll.create_index = AsyncMock()
    return coll


@pytest.fixture()
def mock_db_patch(mock_collection):
    """Patch `shared.db.get_db` to return a mock db backed by `mock_collection`.

    Only effective for consumers that import `get_db` lazily inside a function
    body (attachment_validator, markdown_validator). Consumers that bind
    `get_db` at import time (orchestrator, update_checker, processor,
    crawl_health) are NOT covered — patch their own binding site instead.
    """
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)

    async def fake_get_db():
        return mock_db

    with patch("skkuverse_crawler.shared.db.get_db", side_effect=fake_get_db):
        yield mock_collection
