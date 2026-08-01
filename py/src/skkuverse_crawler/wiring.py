"""Composition root — with the CLI leaves, the only place plugins are
imported (adr-006 결정 ①, invariant amended in PR 7).

Assembly happens here so the crawl logic never reaches for its
dependencies: modules/ receives ports and hooks, it does not fetch them.
The AST rule (tests/structure test_modules_do_not_import_plugins) enforces
the modules→plugins ban; for shared/ the rule is convention.

Ports bundles are built PER RUN, never cached. MongoSink._prepared and
its touch buffer are instance state: a reused bundle would skip
ensure_indexes on the second run, and a failed final flush would leak its
touches into the next one.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from motor.motor_asyncio import AsyncIOMotorCollection

from .core import registry
from .core.module import CrawlModule
from .core.ports import Ports, SeenIndex, Sink, WorkSeed
from .plugins.mongo.seen import MongoSeenIndex
from .plugins.mongo.sink import MongoSink
from .plugins.mongo.work_seed import MongoWorkSeed
from .shared.logger import get_logger

__all__ = ["WiringError", "build_notices_runtime", "build_runtime"]

logger = get_logger("wiring")

PortsFactory = Callable[[], Awaitable[tuple[Ports, SeenIndex]]]


class WiringError(RuntimeError):
    """An adapter does not satisfy the port it was assembled into."""


def _require(obj: object, proto: type, what: str, methods: str) -> None:
    """Assembly-time protocol check (adr-006 결정 ⑦).

    runtime_checkable only verifies method NAMES, not signatures — enough
    to turn a missing flush into a clear boot error instead of an
    AttributeError three hours into a crawl. Runs once per assembly, never
    in the loop.
    """
    if not isinstance(obj, proto):
        raise WiringError(
            f"{type(obj).__name__} does not satisfy the {what} protocol (expected: {methods})"
        )


def build_notices_runtime(
    collection: AsyncIOMotorCollection,
) -> tuple[Ports, SeenIndex]:
    """The seen index is returned separately — it belongs to CrawlMode
    (Incremental(seen)), not to the ports bundle."""
    sink = MongoSink(collection)
    work_seed = MongoWorkSeed(collection)
    seen = MongoSeenIndex(collection)
    _require(sink, Sink, "Sink", "prepare/accept/flush")
    _require(work_seed, WorkSeed, "WorkSeed", "pending_refs")
    _require(seen, SeenIndex, "SeenIndex", "lookup")
    return Ports(sink=sink, work_seed=work_seed), seen


async def notices_ports() -> tuple[Ports, SeenIndex]:
    """The production ports factory — one fresh bundle per call."""
    from .shared.db import get_db

    db = await get_db()
    return build_notices_runtime(db["notices"])


def build_runtime() -> tuple[CrawlModule, ...]:
    """Assemble the scheduler's modules and register them.

    Arg-less for now; `settings`/`profile` (and the boot refusal they
    enable) arrive in PR 8 with the packaging extras that make "this
    plugin is absent" an expressible state.
    """
    from .crawl_health.module import CrawlHealthSummaryModule
    from .crawl_health.store import record_and_alert
    from .modules.notices.module import NoticesModule
    from .notices_summary.module import NoticesSummaryModule
    from .plugins.mongo.update_checker import NoticesUpdateCheckModule

    modules: tuple[CrawlModule, ...] = (
        NoticesModule(ports_factory=notices_ports, on_results=record_and_alert),
        NoticesUpdateCheckModule(),
        NoticesSummaryModule(),
        CrawlHealthSummaryModule(),
    )
    for module in modules:
        registry.register(module)

    logger.info(
        "active_plugins",
        plugins=["mongo"],
        modules=[m.config.name for m in modules],
    )
    return modules
