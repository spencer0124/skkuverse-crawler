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

import functools
import importlib.util
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from .core import registry
from .core.module import CrawlModule
from .core.ports import Notifier, Ports, SeenIndex, Sink, WorkSeed
from .core.settings import Config, CrawlerEnv
from .shared.logger import get_logger

if TYPE_CHECKING:
    # Annotation-only, and motor is an optional dependency now: importing
    # this module must not require the mongo extra.
    from motor.motor_asyncio import AsyncIOMotorCollection

__all__ = ["ProfileError", "WiringError", "build_notices_runtime", "build_runtime"]

logger = get_logger("wiring")

PortsFactory = Callable[[], Awaitable[tuple[Ports, SeenIndex]]]

# plugin -> (a distribution its extra installs, is it configured?)
#
# The marker only answers "is the code installed". Whether it is usable is
# a config question, so both are checked. discord/ai/dispatch share
# tenacity and therefore cannot be told apart by marker alone — their
# predicates carry that weight. The one that matters operationally, mongo,
# is exact on both counts.
_PLUGIN_PROBES: dict[str, tuple[str, Callable[[Config], bool]]] = {
    "mongo": ("motor", lambda s: bool(s.mongo_url)),
    "sched": ("apscheduler", lambda s: True),
    "discord": ("tenacity", lambda s: bool(s.discord_webhook_url)),
    "ai": ("tenacity", lambda s: bool(s.ai_service_url)),
    "dispatch": ("tenacity", lambda s: bool(s.dispatch_url and s.internal_dispatch_token)),
}

# Without these, `start` is not a crawler — it is a bandwidth bill.
REQUIRED_IN_PRODUCTION = ("mongo", "sched")


class WiringError(RuntimeError):
    """An adapter does not satisfy the port it was assembled into."""


class ProfileError(RuntimeError):
    """A required plugin is missing or unconfigured for this profile."""


def _installed(distribution: str) -> bool:
    try:
        return importlib.util.find_spec(distribution) is not None
    except ModuleNotFoundError:
        return False


def active_plugins(settings: Config) -> tuple[str, ...]:
    """Which plugins are both installed and configured, right now.

    Derived rather than declared: a hardcoded list is exactly what goes
    stale, and the whole point of logging this is to notice when a
    deployment lost a plugin.
    """
    return tuple(
        name
        for name, (marker, configured) in _PLUGIN_PROBES.items()
        if _installed(marker) and configured(settings)
    )


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
    from .plugins.mongo.seen import MongoSeenIndex
    from .plugins.mongo.sink import MongoSink
    from .plugins.mongo.work_seed import MongoWorkSeed

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


def _refuse_if_required_plugins_are_missing(settings: Config, profile: CrawlerEnv) -> None:
    """Boot-time gate for the failure extras introduce (plan 위험 ⑤).

    "No mongo plugin" is now a legitimate state, which means a production
    deployment that lost MONGO_URL — or an image built without the extra —
    would crawl all 136 sources, fetch every detail page, write nothing,
    and log a clean success. Worse than known-issues §7, which at least
    blocked the crawl.

    Refusing here makes that loud, and makes the deploy pipeline's
    "container is running after 10s" health check mean something: the
    process exits non-zero in under two seconds and the existing rollback
    fires.
    """
    if profile != CrawlerEnv.PRODUCTION:
        return

    problems = []
    for name in REQUIRED_IN_PRODUCTION:
        marker, configured = _PLUGIN_PROBES[name]
        if not _installed(marker):
            problems.append(
                f"plugin {name!r} is not installed — the image needs "
                f"`--extra {name}` (provides {marker})"
            )
        elif not configured(settings):
            problems.append(f"plugin {name!r} is installed but not configured")

    if problems:
        raise ProfileError(
            "refusing to start in the production profile:\n  - "
            + "\n  - ".join(problems)
            + "\nStarting anyway would crawl every source and store nothing."
        )


def build_runtime(
    settings: Config | None = None,
    *,
    profile: CrawlerEnv | None = None,
) -> tuple[CrawlModule, ...]:
    """Assemble the scheduler's modules and register them.

    ``profile`` defaults to the settings' own environment; pass it
    explicitly to assemble as if for another environment (tests do).
    """
    if settings is None:
        from .env import get_config

        settings = get_config()
    if profile is None:
        profile = settings.env

    _refuse_if_required_plugins_are_missing(settings, profile)

    from .modules.notices.module import NoticesModule
    from .plugins.ai_summary.module import NoticesSummaryModule
    from .plugins.discord.webhook import DiscordNotifier
    from .plugins.health.module import CrawlHealthSummaryModule
    from .plugins.health.store import record_and_alert
    from .plugins.mongo.update_checker import NoticesUpdateCheckModule

    notifier: Notifier = DiscordNotifier()
    _require(notifier, Notifier, "Notifier", "notify")

    modules: tuple[CrawlModule, ...] = (
        NoticesModule(
            ports_factory=notices_ports,
            on_results=functools.partial(record_and_alert, notifier=notifier),
        ),
        NoticesUpdateCheckModule(),
        NoticesSummaryModule(),
        CrawlHealthSummaryModule(notifier),
    )
    for module in modules:
        registry.register(module)

    logger.info(
        "active_plugins",
        plugins=list(active_plugins(settings)),
        profile=profile.value,
        modules=[m.config.name for m in modules],
    )
    return modules
