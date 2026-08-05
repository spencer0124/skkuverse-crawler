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
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
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

__all__ = [
    "ModuleFamily",
    "ProfileError",
    "UnknownModuleError",
    "WiringError",
    "build_bus_runtime",
    "build_notices_runtime",
    "build_runtime",
    "known_module_names",
]

logger = get_logger("wiring")

PortsFactory = Callable[[], Awaitable[tuple[Ports, SeenIndex]]]

# ── bus migration switches ────────────────────────────────────────────────
#
# Until the cutover the crawler writes BESIDE skkuverse-server rather than
# over it: `hssc__shadow`, not `hssc`. Flipping this to False IS the
# cutover, and must not happen before the server stops writing those ids —
# two writers on one `_id` is last-writer-wins, and the "compare the two"
# step the migration rests on would have nothing left to compare.
BUS_SHADOW_WRITES = True

# The server's BusCacheService honours a MONGO_CACHE_COLLECTION override.
# No deployment sets it and `.env.example` pins it to this default; if one
# ever does, this needs the same Config field or the crawler writes to a
# collection nobody reads — with no error anywhere.
BUS_CACHE_COLLECTION = "bus_cache"

# campus_eta lives OUTSIDE bus_cache. That collection carries the server's
# `ttl_updatedAt` index (expireAfterSeconds 60) and SnapshotSink stamps
# `_updatedAt` on every write, so a ten-minute cadence would leave the
# document present for sixty seconds out of every six hundred. hssc (10s)
# and jongro (40s) refresh well inside the window; this one cannot.
CAMPUS_ETA_COLLECTION = "campus_eta"

# Consecutive down-ticks before a Discord alert. Per module, because ticks
# are not comparable across cadences: plugins/health's THRESHOLD of 3 is
# ninety minutes of the half-hourly notices crawl and thirty SECONDS of the
# HSSC poller. These are all roughly five minutes, except campus ETA, where
# five minutes is less than one tick.
HSSC_ALERT_TICKS = 30  # 10s  × 30 = 5 min
JONGRO_ALERT_TICKS = 8  # 40s  × 8  ≈ 5 min
CAMPUS_ETA_ALERT_TICKS = 3  # 600s × 3  = 30 min

# plugin -> (a distribution its extra installs, is it configured?)
#
# The marker only answers "is the code installed". Whether it is usable is
# a config question, so both are checked. discord/ai/dispatch all install
# tenacity and cannot be told apart by marker alone; their predicates carry
# that weight, so a predicate that cannot be False makes its plugin
# unconditionally "active" and the log stops being evidence.
#
# `ai` is exactly that case and is deliberately marker-only: ai_service_url
# always has a value (core.settings.default_ai_service_url), so there is no
# configuration that says "no AI". Reporting it whenever the code is
# installed is the honest reading — reachability is not a config question
# and is not claimed here.
_PLUGIN_PROBES: dict[str, tuple[str, Callable[[Config], bool]]] = {
    "mongo": ("motor", lambda s: bool(s.mongo_url)),
    "sched": ("apscheduler", lambda s: True),
    "discord": ("tenacity", lambda s: bool(s.discord_webhook_url)),
    "ai": ("tenacity", lambda s: True),
    "dispatch": ("tenacity", lambda s: bool(s.dispatch_url and s.internal_dispatch_token)),
}

# Two different requirements, deliberately separate.
#
# INSTALLED is everything build_runtime imports unconditionally. Leaving
# discord/ai out would let the gate pass and the process die three lines
# later on `import tenacity` — loud, but without the message naming the
# missing --extra, which is the gate's whole purpose.
#
# CONFIGURED is narrower, and only mongo belongs in it. A production
# deployment with no Discord webhook is a documented, supported state
# (alerts are skipped and the boot log says so); refusing to start over it
# would take the crawler down for a missing nice-to-have.
REQUIRED_INSTALLED = ("mongo", "sched", "discord", "ai")
REQUIRED_CONFIGURED = ("mongo",)


class WiringError(RuntimeError):
    """An adapter does not satisfy the port it was assembled into."""


class ProfileError(RuntimeError):
    """A required plugin is missing or unconfigured for this profile."""


class UnknownModuleError(RuntimeError):
    """A requested module name does not exist in any family.

    Loud on purpose. The filter used to be a silent match: `--module
    notice` (singular) selected nothing, the scheduler added zero jobs,
    and the container sat there healthy and idle.
    """


@dataclass(frozen=True)
class ModuleFamily:
    """Modules that ship and configure together.

    ``module_names`` is declared rather than discovered so that selection
    and the config gate can both be answered BEFORE anything is built —
    otherwise refusing to boot would require importing the very plugins
    the refusal says are missing. ``build_runtime`` checks the declaration
    against what the builder actually returned, so the duplication cannot
    rot silently.

    ``requires`` names ``Config`` attributes that must be truthy for the
    family to run at all. Absent in production is a refusal; absent
    anywhere else means the family is skipped with a log, so a developer
    without a third party's API key still gets the rest of the crawler.
    """

    name: str
    module_names: tuple[str, ...]
    requires: tuple[str, ...]
    build: Callable[[Config, Notifier], tuple[CrawlModule, ...]]


def _build_notices(settings: Config, notifier: Notifier) -> tuple[CrawlModule, ...]:
    from .modules.notices.module import NoticesModule
    from .plugins.ai_summary.module import NoticesSummaryModule
    from .plugins.health.module import CrawlHealthSummaryModule
    from .plugins.health.probes import bus_probe, notices_probe
    from .plugins.health.store import record_and_alert
    from .plugins.mongo.update_checker import NoticesUpdateCheckModule

    return (
        NoticesModule(
            ports_factory=notices_ports,
            on_results=functools.partial(
                record_and_alert, notifier=notifier, label="notices"
            ),
        ),
        NoticesUpdateCheckModule(),
        NoticesSummaryModule(),
        # The summary itself is family-agnostic; what it reports on comes
        # in as probes. A second family adds its own here rather than
        # needing a second daily message.
        #
        # bus_probe() rides along even in a notices-only container, and has
        # to: run_daily_summary filters the failing list to enabled ids, so
        # without it a bus poller stuck down would be dropped from the
        # 09:00 message instead of headlining it. It reads three enum
        # values and needs no bus credentials.
        CrawlHealthSummaryModule(notifier, probes=(notices_probe(), bus_probe())),
    )


def _build_bus(settings: Config, notifier: Notifier) -> tuple[CrawlModule, ...]:
    from .modules.bus.module import BusHsscModule, BusJongroModule
    from .plugins.health.store import record_and_alert

    def alerts(threshold: int):
        return functools.partial(
            record_and_alert, notifier=notifier, threshold=threshold, label="bus"
        )

    return (
        BusHsscModule(
            sink_factory=bus_cache_ports,
            endpoint=settings.hssc_api_url or "",
            shadow_writes=BUS_SHADOW_WRITES,
            on_results=alerts(HSSC_ALERT_TICKS),
        ),
        BusJongroModule(
            sink_factory=bus_cache_ports,
            service_key=settings.seoul_bus_service_key or "",
            shadow_writes=BUS_SHADOW_WRITES,
            on_results=alerts(JONGRO_ALERT_TICKS),
        ),
    )


def _build_bus_eta(settings: Config, notifier: Notifier) -> tuple[CrawlModule, ...]:
    from .modules.bus.module import BusCampusEtaModule
    from .plugins.health.store import record_and_alert

    return (
        BusCampusEtaModule(
            sink_factory=campus_eta_ports,
            api_key_id=settings.naver_api_key_id or "",
            api_key=settings.naver_api_key or "",
            shadow_writes=BUS_SHADOW_WRITES,
            on_results=functools.partial(
                record_and_alert,
                notifier=notifier,
                threshold=CAMPUS_ETA_ALERT_TICKS,
                label="bus-eta",
            ),
        ),
    )


_FAMILIES: tuple[ModuleFamily, ...] = (
    ModuleFamily(
        name="notices",
        module_names=(
            "notices",
            "notices-update-check",
            "notices-summary",
            "crawl-health-summary",
        ),
        # Nothing beyond mongo, which the plugin probes already cover.
        requires=(),
        build=_build_notices,
    ),
    ModuleFamily(
        name="bus",
        module_names=("bus-hssc", "bus-jongro"),
        requires=("mongo_bus_db_name", "hssc_api_url", "seoul_bus_service_key"),
        build=_build_bus,
    ),
    # Separate from `bus`, not folded into it. A family is "modules that
    # ship and configure together", and these do not: the credentials come
    # from a different issuer (Naver Cloud, not SKKU + Seoul TOPIS), the
    # cadence is sixty times slower, and the storage is a different
    # collection. Folded together, a lapsed Naver key would be an
    # unconfigured selected family — which in production is a boot refusal
    # — and would take the shuttle board down with it.
    ModuleFamily(
        name="bus-eta",
        module_names=("bus-campus-eta",),
        requires=("mongo_bus_db_name", "naver_api_key_id", "naver_api_key"),
        build=_build_bus_eta,
    ),
)


def known_module_names() -> tuple[str, ...]:
    """Every module name any family declares, in declaration order.

    Duplicates are a build error rather than a curiosity: registry keys on
    the name and would silently drop one of the two, and the scheduler
    (which now sets job id = module name) would raise ConflictingIdError
    at start — after the registry already lost a module. Cheaper to say so
    here.
    """
    names = tuple(name for family in _FAMILIES for name in family.module_names)
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise WiringError(
            f"module name(s) declared by more than one family: {', '.join(duplicates)}"
        )
    return names


def _resolve_selection(selection: Sequence[str] | None) -> set[str] | None:
    """None means every module. Otherwise every name must exist."""
    if selection is None:
        return None
    wanted = {name.strip() for name in selection if name.strip()}
    known = set(known_module_names())
    unknown = sorted(wanted - known)
    if unknown:
        raise UnknownModuleError(
            f"unknown module(s): {', '.join(unknown)}. "
            f"Valid names are: {', '.join(sorted(known))}"
        )
    if not wanted:
        raise UnknownModuleError(
            "no modules selected — omit the option to run all of them, "
            f"or name some of: {', '.join(sorted(known))}"
        )
    return wanted


def _missing_config(settings: Config, family: ModuleFamily) -> tuple[str, ...]:
    """Which of the family's required Config attributes are absent.

    A name that is not a Config field at all is a typo in _FAMILIES, not a
    deployment that forgot a variable — and `getattr(..., None)` would make
    the two indistinguishable, refusing production over an attribute that
    does not exist and silently skipping the family everywhere else.
    """
    unknown = [name for name in family.requires if not hasattr(settings, name)]
    if unknown:
        raise WiringError(
            f"module family {family.name!r} requires {unknown}, which "
            f"{type(settings).__name__} does not define — fix _FAMILIES"
        )
    return tuple(name for name in family.requires if not getattr(settings, name))


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


def build_bus_runtime(collection: AsyncIOMotorCollection) -> Sink:
    """The snapshot archetype's whole assembly: one sink, no seen index,
    no work seed. `SnapshotSink` has no instance state — no prepare guard,
    no write buffer — so unlike MongoSink it would be safe to cache. It is
    still built per call, because the reason not to cache is the same one
    that applies to any collection handle: the client can be closed and
    reopened underneath it."""
    from .plugins.mongo.snapshot import SnapshotSink

    sink = SnapshotSink(collection)
    _require(sink, Sink, "Sink", "prepare/accept/flush")
    return sink


async def _bus_collection(name: str) -> AsyncIOMotorCollection:
    """Resolve a collection in the BUS database, never the notices one.

    The explicit emptiness check is the point. `get_db(None)` falls back to
    `Config.mongo_db_name`, so a missing `MONGO_DB_NAME_BUS_CAMPUS` would
    not fail — it would quietly write bus_cache documents into
    skku_notices, where nothing reads them and nothing complains. The
    family gate refuses that configuration before this runs; this is the
    guard for everything that does not come through the gate.
    """
    from .env import get_config
    from .shared.db import get_db

    db_name = get_config().mongo_bus_db_name
    if not db_name:
        raise WiringError(
            "the bus database is not configured (MONGO_DB_NAME_BUS_CAMPUS) — "
            "without it the bus modules would write into the notices database"
        )
    db = await get_db(db_name)
    return db[name]


async def bus_cache_ports() -> Sink:
    """Realtime shuttle/Jongro documents — the collection skkuverse-server
    already owns, and whose 60-second TTL index governs these writes."""
    return build_bus_runtime(await _bus_collection(BUS_CACHE_COLLECTION))


async def campus_eta_ports() -> Sink:
    """Campus ETA, in its own collection. See CAMPUS_ETA_COLLECTION for why
    it is not in bus_cache."""
    return build_bus_runtime(await _bus_collection(CAMPUS_ETA_COLLECTION))


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
    for name in REQUIRED_INSTALLED:
        marker, _configured = _PLUGIN_PROBES[name]
        if not _installed(marker):
            problems.append(
                f"plugin {name!r} is not installed — the image needs "
                f"`--extra {name}` (provides {marker})"
            )
    for name in REQUIRED_CONFIGURED:
        marker, configured = _PLUGIN_PROBES[name]
        if _installed(marker) and not configured(settings):
            problems.append(f"plugin {name!r} is installed but not configured")

    if problems:
        raise ProfileError(
            "refusing to start in the production profile:\n  - "
            + "\n  - ".join(problems)
            + "\nStarting anyway would crawl every source and store nothing."
        )


def _refuse_if_a_selected_family_is_unconfigured(
    settings: Config, profile: CrawlerEnv, families: list[ModuleFamily]
) -> None:
    """Same refusal, one level up: a family this process was ASKED to run
    but cannot.

    Keyed on the selection rather than on which variables happen to be
    set. That distinction is what makes split containers possible — a
    notices-only process must not refuse to boot because the bus keys are
    absent from its environment, and a bus process must not start
    pretending it has them.
    """
    if profile != CrawlerEnv.PRODUCTION:
        return

    problems = [
        f"module family {f.name!r} is selected but unconfigured "
        f"(missing: {', '.join(_missing_config(settings, f))})"
        for f in families
        if _missing_config(settings, f)
    ]
    if problems:
        raise ProfileError(
            "refusing to start in the production profile:\n  - "
            + "\n  - ".join(problems)
            + "\nIts modules would run every tick and fail every tick."
        )


def build_runtime(
    settings: Config | None = None,
    *,
    profile: CrawlerEnv | None = None,
    selection: Sequence[str] | None = None,
) -> tuple[CrawlModule, ...]:
    """Assemble the scheduler's modules and register them.

    ``profile`` defaults to the settings' own environment; pass it
    explicitly to assemble as if for another environment (tests do).

    ``selection`` names the modules this process should run; None means
    all of them. Selection happens HERE rather than in the scheduler so
    that only what will actually run gets built — which is what lets a
    notices-only container boot without the bus family's credentials.
    """
    if settings is None:
        from .env import get_config

        settings = get_config()
    if profile is None:
        profile = settings.env

    wanted = _resolve_selection(selection)
    families = [
        f for f in _FAMILIES if wanted is None or (set(f.module_names) & wanted)
    ]

    _refuse_if_required_plugins_are_missing(settings, profile)
    _refuse_if_a_selected_family_is_unconfigured(settings, profile, families)

    from .plugins.discord.webhook import DiscordNotifier

    notifier: Notifier = DiscordNotifier()
    _require(notifier, Notifier, "Notifier", "notify")

    modules: list[CrawlModule] = []
    for family in families:
        missing = _missing_config(settings, family)
        if missing:
            # Production already refused above; here it is a developer
            # without someone else's API key, and the rest must still run.
            logger.info(
                "module_family_skipped", family=family.name, missing=list(missing)
            )
            continue
        built = family.build(settings, notifier)
        _assert_declaration_matches(family, built)
        modules.extend(m for m in built if wanted is None or m.config.name in wanted)

    if not modules:
        # Reached when every selected family was skipped for missing
        # config. The skip's justification — "a developer without a third
        # party's API key still gets the rest of the crawler" — does not
        # hold when the selection WAS that family: there is no rest, and
        # run_scheduler would add zero jobs and block on the signal
        # forever. Same healthy-and-idle container UnknownModuleError
        # exists to prevent, reached through the config door instead of
        # the name door, so it is refused in every profile.
        raise ProfileError(
            "refusing to start: every selected module family is unconfigured, "
            "so there is nothing to run. Configure one, or select a family "
            f"that is. Known modules: {', '.join(sorted(known_module_names()))}"
        )

    for module in modules:
        registry.register(module)

    logger.info(
        "active_plugins",
        plugins=list(active_plugins(settings)),
        profile=profile.value,
        modules=[m.config.name for m in modules],
    )
    return tuple(modules)


def _assert_declaration_matches(
    family: ModuleFamily, built: tuple[CrawlModule, ...]
) -> None:
    """The family table is a second source of truth for module names, and
    the gate reads it before anything is imported. Drift would mean either
    refusing to boot over a module that no longer exists, or booting a
    module whose config was never checked — so check it every assembly."""
    # Compared as sets: the declaration exists so the gate can answer
    # "can this family run" before importing anything, and nothing
    # downstream cares what order a family builds in. Order-sensitivity
    # here would fail the boot over a reshuffle, listing the same names on
    # both sides of the message.
    actual = tuple(m.config.name for m in built)
    if set(actual) != set(family.module_names) or len(actual) != len(
        family.module_names
    ):
        raise WiringError(
            f"module family {family.name!r} declares "
            f"{sorted(family.module_names)} but built {sorted(actual)} "
            f"— update _FAMILIES"
        )
