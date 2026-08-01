"""Composition root — the ONLY module that may import plugins.* (adr-006;
pinned by tests/structure test_modules_do_not_import_plugins, which bans
plugins imports under modules/).

TEMPORARY EDGE (PR 5 → PR 7): modules/notices reaches up here via *lazy*
function-body imports until PR 7 inverts injection (entry points receive
ports from wiring). The laziness is load-bearing — PR 7's wiring will
import modules/notices/module.py, which imports orchestrator and
update_checker at module level; an eager import here would then cycle.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorCollection

from .core.ports import Ports
from .plugins.mongo.seen import MongoSeenIndex
from .plugins.mongo.sink import MongoSink, ensure_indexes
from .plugins.mongo.work_seed import MongoWorkSeed

__all__ = ["build_notices_ports", "ensure_notice_indexes"]

# Shim for modules/notices/update_checker (its only former dedup import);
# retired in PR 7 when update_checker moves into plugins/mongo.
ensure_notice_indexes = ensure_indexes


def build_notices_ports(collection: AsyncIOMotorCollection) -> Ports:
    return Ports(
        seen=MongoSeenIndex(collection),
        sink=MongoSink(collection),
        work_seed=MongoWorkSeed(collection),
    )
