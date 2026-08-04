from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from ..env import get_config

_client: AsyncIOMotorClient | None = None


class MongoUrlMissing(RuntimeError):
    """MONGO_URL is unset but something asked for a database.

    Since PR 8 this is no longer caught at config load — "no store" is a
    legitimate configuration (`notices --json` runs that way). So the
    requirement is enforced where a store is actually needed, and it must
    be enforced: AsyncIOMotorClient(None) does not fail, it quietly
    connects to localhost:27017.
    """

    def __init__(self) -> None:
        super().__init__(
            "MONGO_URL is not set — set it, or use a command that does not "
            "need a store (e.g. `notices --json`)"
        )


async def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        mongo_url = get_config().mongo_url
        if not mongo_url:
            raise MongoUrlMissing()
        _client = AsyncIOMotorClient(mongo_url, maxPoolSize=5, minPoolSize=1)
    return _client


async def get_db(name: str | None = None) -> AsyncIOMotorDatabase:
    """The notices database by default; pass a name for any other.

    One client, many databases: modules do not share a schema and need not
    share a database. The default keeps every existing caller unchanged.
    An empty name is refused rather than silently handed to the driver,
    which would resolve it against the connection string's default and put
    documents somewhere nobody asked for.
    """
    client = await get_client()
    if name is not None and not name:
        raise ValueError("database name is empty — pass None for the default, not ''")
    return client[name or get_config().mongo_db_name]


async def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
