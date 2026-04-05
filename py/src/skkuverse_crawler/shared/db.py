from __future__ import annotations

import os

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

_client: AsyncIOMotorClient | None = None


def _get_db_name() -> str:
    base = os.getenv("MONGO_DB_NAME", "skku_notices")
    env = os.getenv("CRAWLER_ENV", "production")
    if env in ("development", "test"):
        suffix = "_test" if env == "test" else "_dev"
        return f"{base}{suffix}"
    return base


async def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        url = os.getenv("MONGO_URL")
        if not url:
            raise RuntimeError("MONGO_URL is not set")
        _client = AsyncIOMotorClient(url, maxPoolSize=5, minPoolSize=1)
    return _client


async def get_db() -> AsyncIOMotorDatabase:
    client = await get_client()
    return client[_get_db_name()]


async def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
