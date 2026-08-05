from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from skkuverse_crawler.env import init_config, reset_config


@pytest.fixture(autouse=True)
def _test_env_and_config(monkeypatch):
    """Give every test an explicitly initialized test-mode config, built
    from ``os.environ`` alone.

    Since PR 1 get_config() no longer lazy-initializes (it raises
    ConfigNotInitialized), so this fixture calls init_config() itself.
    CRAWLER_ENV=test is still load-bearing on its own: it selects the
    *_test DB-name suffix, the CRITICAL log level, and the is_test guard
    that waives the MONGO_URL requirement inside init_config().

    ``load_dotenv`` is stubbed out for the duration, and that is not a
    convenience — it is what makes the suite mean the same thing on a
    developer's machine as it does in CI. The real one mutates
    ``os.environ`` **permanently**, so a single init_config() leaks every
    value in ``py/.env`` into the process for the rest of the session.
    Tests that assert "unset reads as None" then delete a variable and
    watch init_config(force=True) put it straight back — and they pass
    anyway, right up until someone's .env grows the key they were testing.
    That is exactly how the bus tests broke: they were only ever green
    because nobody had bus credentials locally.

    Anything a test needs, it sets.
    """
    reset_config()
    monkeypatch.setenv("CRAWLER_ENV", "test")
    with patch("skkuverse_crawler.env.load_dotenv"):
        init_config(force=True)
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
    body — `plugins/mongo/audit.py` and `wiring.notices_ports`. Consumers that
    bind `get_db` at import time (plugins/mongo/update_checker,
    plugins/ai_summary/processor, plugins/health) are NOT covered — patch
    their own binding site instead.

    The orchestrator dropped off this list in PR 7: it no longer imports
    get_db at all, because it receives ports instead of fetching them.
    """
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)

    async def fake_get_db(name=None):
        # `get_db` takes an optional database name since bus started
        # writing to its own database. A zero-arg fake would make every
        # `get_db(name)` caller fail with a TypeError that names the fixture
        # rather than the code under test.
        return mock_db

    with patch("skkuverse_crawler.shared.db.get_db", side_effect=fake_get_db):
        yield mock_collection
