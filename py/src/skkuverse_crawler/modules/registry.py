from __future__ import annotations

from .base import CrawlModule

_modules: dict[str, CrawlModule] = {}


def register(module: CrawlModule) -> None:
    _modules[module.config.name] = module


def get_module(name: str) -> CrawlModule:
    return _modules[name]


def all_modules() -> list[CrawlModule]:
    return list(_modules.values())
