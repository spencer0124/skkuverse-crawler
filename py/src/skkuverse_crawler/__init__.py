"""SKKU notice crawler — fetch, clean and structure university notices.

    from skkuverse_crawler import iter_notices

    async for notice in iter_notices("skku-main"):
        print(notice.date, notice.title)

For anything beyond reading notices — plugging in storage, consuming the
event stream, writing a sink — start at ``skkuverse_crawler.core``.

**Lazy on purpose.** Both names below are resolved through PEP 562
``__getattr__`` rather than imported at the top. Importing any submodule
executes this file first, so an eager ``from .modules.notices.simple
import iter_notices`` here would make ``import
skkuverse_crawler.core.ports`` drag in the strategies, bs4, lxml and
httpx. The infra-free tests would stay green while the core quietly
stopped being cheap to import — the failure mode that has no alarm, so it
gets structure instead of a test.

Reaching across into ``modules`` at all is fine here for the same reason
it is fine in ``cli.py`` and ``wiring.py``: this is an assembly leaf.
Nothing inside the package imports it for its contents.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Not redundant with __getattr__ below: without this, mypy types
    # `iter_notices` as Any and silently stops checking every caller of
    # the facade — including the examples CI runs.
    from .modules.notices.simple import iter_notices as iter_notices

__all__ = ["__version__", "iter_notices"]


def __getattr__(name: str) -> Any:
    if name == "iter_notices":
        from .modules.notices.simple import iter_notices

        return iter_notices
    if name == "__version__":
        # importlib.metadata, not a hardcoded string: pyproject.toml is the
        # single source and a second copy here is one that goes stale.
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("skkuverse-crawler")
        except PackageNotFoundError:  # pragma: no cover - source tree, not installed
            return "0.0.0+unknown"
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    # Without this, tab completion and dir() show neither name — module
    # __getattr__ is invisible to the default __dir__.
    return sorted(__all__)
