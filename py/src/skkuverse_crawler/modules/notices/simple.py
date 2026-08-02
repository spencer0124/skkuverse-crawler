"""The one-liner entry point: notices out, no assembly required.

``iter_source`` yields the full event vocabulary and expects a strategy, a
crawl mode, a work seed and a logger. That is the right shape for someone
plugging in storage, and the wrong shape for someone who wants to read a
department's notices. This module is the second door, not a second
implementation — it filters ``iter_source`` and assembles its arguments,
and contains zero lines of crawl logic (adr-006 §⑨: "두 번째 경로 금지"
bans duplicating the logic, not having more than one entrance).

Why here and not ``core/simple.py`` as the design sketch had it: PR 6
settled ``iter_source`` in this module, because it depends on the crawl
policy, ``build_notice`` and image verification — all content semantics
this module owns. ``core`` must not import ``modules``, so a facade in
core could not call the thing it is a facade over. The nice import path
is recovered at the package top level, which is an assembly leaf like
``cli.py`` and ``wiring.py`` and may reach across layers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import aclosing
from typing import Any

from ...core.crawl import FullSweep
from ...core.events import NoticeCrawled
from ...core.ports import NullWorkSeed
from ...shared.fetcher import Fetcher
from ...shared.logger import get_logger
from .config.loader import load_and_validate
from .constants import SERVICE_START_DATE
from .models import Notice
from .orchestrator import CrawlOptions, iter_source
from .strategies import STRATEGY_MAP

__all__ = ["DEFAULT_MAX_PAGES", "iter_notices"]

# One page, not the FullSweep default of 2500. A store-less crawl cannot
# be incremental, so max_pages is the only thing standing between a first
# `iter_notices("skku-main")` and a full historical sweep of a university
# server. The CLI's --json path imports this same constant so the two
# casual entry points cannot drift apart.
DEFAULT_MAX_PAGES = 1

# The default is the ordinary module logger, NOT a silent stub. A stub was
# tried and removed: it silences only the crawl loop, while the config
# loader and every strategy hold their own module-level structlog loggers
# that no argument here can reach. The result was a partial silence —
# strategy fetch lines visible, the loop's own stopping reason hidden —
# which reads worse than either extreme.
#
# Verbosity belongs to the application, and structlog already owns that
# control point. Two lines at the top of a caller's script silence
# everything, including these:
#
#     structlog.configure(
#         wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL))
#
# A library must not make that call itself: structlog config is process
# global, and a facade that reconfigures logging on import would be a far
# nastier surprise than a few log lines. examples/quickstart.py shows it.
logger = get_logger("notices.simple")


def _resolve(source: str | Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(source, str):
        return dict(source)

    for candidate in load_and_validate():
        if candidate.get("id") == source:
            return candidate

    # ValueError, not SourceConfigError: the config file is fine, the
    # caller made a typo. run_crawl draws the same line for an unknown
    # --source.
    raise ValueError(f"unknown source id: {source!r} — see sources.json for valid ids")


async def iter_notices(
    source: str | Mapping[str, Any],
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    delay_ms: int = 500,
    since_date: str | None = SERVICE_START_DATE,
    log: Any = None,
) -> AsyncIterator[Notice]:
    """Yield the notices of one source. No store, no configuration, no env.

    ``source`` is a department id from ``sources.json`` (``"skku-main"``),
    or a source dict of your own if you are not using the bundled config.

    This is a full sweep by definition — with nothing to compare against,
    every item is new — so it walks back only ``max_pages`` pages and stops
    at ``since_date``. Raise ``max_pages`` to go deeper.

    An explicit id wins over the cron filters: unlike the scheduled crawl,
    this does not consult ``crawlAvailable``/``crawlEnabled``. Asking for a
    source by name is a stronger signal than a deployment default.

    The crawl logs through structlog like the rest of the package; pass
    ``log`` to redirect just this crawl's loop, or configure structlog in
    your own program to set the level for everything (see the module
    comment on ``logger`` — the strategies log independently and only
    structlog's own config reaches them).

    Example::

        async for notice in iter_notices("skku-main"):
            print(notice.date, notice.title)

    The HTTP client is closed when iteration ends, including on an early
    ``break`` — as long as the loop is left normally or the generator is
    closed (``contextlib.aclosing``), which ``async for`` does for you.
    """
    dept = _resolve(source)
    strategy_cls = STRATEGY_MAP.get(dept["strategy"])
    if strategy_cls is None:
        raise ValueError(f"unknown strategy: {dept['strategy']!r}")

    fetcher = Fetcher(delay_ms=delay_ms)
    options = CrawlOptions(max_pages=max_pages, delay_ms=delay_ms, since_date=since_date)

    try:
        # aclosing, matching _crawl_department: if the consumer breaks out
        # mid-page the generator is finalized here rather than at GC time,
        # where asyncio's asyncgen hooks make teardown nondeterministic.
        async with aclosing(
            iter_source(
                dept,
                strategy_cls(fetcher),
                mode=FullSweep(),
                work_seed=NullWorkSeed(),
                options=options,
                logger=log if log is not None else logger,
            )
        ) as events:
            async for event in events:
                if isinstance(event, NoticeCrawled):
                    yield event.notice
    finally:
        await fetcher.close()
