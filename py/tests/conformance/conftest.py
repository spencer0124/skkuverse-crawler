"""Real-MongoDB fixtures for the conformance suite (@pytest.mark.mongo).

Backend acquisition: testcontainers first (a container makes writing to a
production cluster structurally impossible), MONGO_TEST_URL as the fallback
for Docker-less environments. Either way each test gets a disposable database
name that is dropped on teardown.
"""
from __future__ import annotations

import os
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient


@pytest.fixture(scope="session")
def mongo_url():
    url = os.environ.get("MONGO_TEST_URL")
    if url:
        yield url
        return
    # Docker Desktop (macOS): the client socket ~/.docker/run/docker.sock cannot
    # be bind-mounted into ryuk; the VM-internal /var/run/docker.sock can.
    os.environ.setdefault("TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE", "/var/run/docker.sock")
    from testcontainers.community.mongodb import MongoDbContainer

    with MongoDbContainer("mongo:7") as container:
        yield container.get_connection_url()


@pytest.fixture()
async def real_collection(mongo_url):
    """A 'notices' collection in a throwaway database on a real MongoDB.

    Function-scoped: the Motor client must be created inside the test's event
    loop (asyncio_mode=auto gives each test a fresh loop).
    """
    client = AsyncIOMotorClient(mongo_url)
    db_name = f"conformance_{uuid.uuid4().hex[:8]}"
    yield client[db_name]["notices"]
    await client.drop_database(db_name)
    client.close()
