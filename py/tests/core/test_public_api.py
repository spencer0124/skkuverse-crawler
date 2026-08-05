"""The public API surface of ``skkuverse_crawler.core``.

Two different jobs here, and only the second one is interesting.

The easy job: every name in ``__all__`` actually resolves. The valuable
job: nothing PUBLIC in the core submodules is *missing* from ``__all__``.
That is the ratchet — a new event class added to ``core/events.py`` and
forgotten here would be invisible to `from skkuverse_crawler.core import
*`, and (worse) would slip past the tier classification that decides
whether adding it was a minor or a major release (adr-006 §⑨).
"""

from __future__ import annotations

import importlib
import inspect

import pytest

from skkuverse_crawler import core

# The submodules whose public names must all be re-exported. `settings`,
# `registry` and `testing` are absent on purpose — core/__init__'s
# docstring records why for each.
PUBLIC_SURFACE = (
    "crawl",
    "events",
    "module",
    "pipeline",
    "ports",
    "results",
    "runner",
    "sinks",
    "sources",
)


def test_every_exported_name_resolves():
    missing = [name for name in core.__all__ if not hasattr(core, name)]
    assert not missing, f"__all__ names that do not exist: {missing}"


def test_all_has_no_duplicates():
    """Named for what it checks. It used to be called
    `test_all_is_sorted_within_no_duplicates` and never checked sortedness
    — __all__ is grouped by tier and role, not sorted, and a name promising
    an assertion nobody wrote is worse than no test."""
    assert len(core.__all__) == len(set(core.__all__)), "duplicate names in __all__"


@pytest.mark.parametrize("submodule", PUBLIC_SURFACE)
def test_public_submodule_names_are_all_re_exported(submodule):
    mod = importlib.import_module(f"skkuverse_crawler.core.{submodule}")
    qualified = f"skkuverse_crawler.core.{submodule}"

    # `__module__` filters out names the submodule merely imported (ports
    # imports nothing public, but events imports DetailRef/SeenRecord and
    # runner imports the whole event vocabulary). Only classes and
    # functions carry it, which is exactly the population that matters:
    # a new event, port or result type. Plain aliases like CrawlMode are
    # listed in __all__ by hand.
    defined_here = {
        name
        for name, obj in vars(mod).items()
        if not name.startswith("_")
        and (inspect.isclass(obj) or inspect.isfunction(obj))
        and getattr(obj, "__module__", None) == qualified
    }

    missing = sorted(defined_here - set(core.__all__))
    assert not missing, (
        f"{qualified} defines {missing} but core/__init__.py does not export them — "
        f"add them to __all__ under the right tier, or rename them private"
    )


def test_settings_and_registry_are_deliberately_not_exported():
    """Pinned, not incidental: exporting Config would freeze this
    deployment's settings shape under the 0.x event promise, and exporting
    the registry would hand out process-global mutable state."""
    for name in ("Config", "CrawlerEnv", "register", "get_module", "all_modules"):
        assert name not in core.__all__, f"{name} leaked into the public API"


def test_result_tier_events_are_all_exported():
    """The frozen tier, listed by hand. If this list and __all__ disagree,
    someone changed the contract without noticing which tier they were in
    (adr-006 §⑧ — misclassifying a result event as progress makes
    third-party sinks lose data silently)."""
    result_tier = {
        "ContentRefreshed",
        "ItemFailed",
        "ItemSkipped",
        "ItemCrawled",
        "ItemUnchanged",
    }
    assert result_tier <= set(core.__all__)
