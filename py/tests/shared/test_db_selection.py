"""Which database `get_db` hands back.

One Motor client, many databases: modules do not share a schema and need
not share a database. Bus writes a cache collection that must not land
next to `notices`, so the selection is worth pinning — a wrong database
name does not raise anywhere, it just writes documents somewhere nobody
looks.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from skkuverse_crawler.shared.db import get_db


class _FakeClient(dict):
    """Motor clients index like a mapping; that is all get_db uses."""

    def __getitem__(self, name):
        return f"db:{name}"


@pytest.fixture
def fake_client():
    with patch("skkuverse_crawler.shared.db.get_client", return_value=_FakeClient()):
        yield


async def test_no_name_means_the_configured_notices_database(fake_client, monkeypatch):
    from skkuverse_crawler.env import get_config

    assert await get_db() == f"db:{get_config().mongo_db_name}"


async def test_an_explicit_name_wins(fake_client):
    assert await get_db("bus_campus_test") == "db:bus_campus_test"


async def test_the_bus_database_is_reachable_from_config(fake_client):
    """The path bus will actually take: read the name off Config rather
    than hardcoding it at the call site."""
    from skkuverse_crawler.env import get_config

    cfg = get_config()
    assert await get_db(cfg.mongo_bus_db_name) == f"db:{cfg.mongo_bus_db_name}"
    assert cfg.mongo_bus_db_name != cfg.mongo_db_name


async def test_an_empty_name_is_refused_rather_than_silently_defaulted(fake_client):
    """`client[""]` does not raise — it resolves against the connection
    string's default database. A caller passing "" has a bug (an unset
    config field, most likely) and should hear about it here, not by
    finding its documents in the wrong place a week later.
    """
    with pytest.raises(ValueError, match="database name is empty"):
        await get_db("")
