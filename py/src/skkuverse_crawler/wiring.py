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
    "build_notices_runtime",
    "build_runtime",
    "known_module_names",
]

logger = get_logger("wiring")

PortsFactory = Callable[[], Awaitable[tuple[Ports, SeenIndex]]]

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
    from .plugins.health.probes import notices_probe
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
        CrawlHealthSummaryModule(notifier, probes=(notices_probe(),)),
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
