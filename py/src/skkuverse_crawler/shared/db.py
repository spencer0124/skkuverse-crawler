from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from .config import get_config

_client: AsyncIOMotorClient | None = None


async def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(
            get_config().mongo_url, maxPoolSize=5, minPoolSize=1,
        )
    return _client


async def get_db() -> AsyncIOMotorDatabase:
    client = await get_client()
    return client[get_config().mongo_db_name]


async def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
