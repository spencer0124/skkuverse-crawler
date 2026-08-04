"""The only module that reads the environment (adr-006 결정 ①).

`os.environ`, `os.getenv` and `load_dotenv` live here and nowhere else, so
that "where does this value come from" has exactly one answer and a
library caller can construct a `Config` without an environment at all.
The invariant is enforced by tests/structure test_env_is_the_only_environment_reader.

The value type lives in `core/settings.py`; this module only fills it in.
The singleton accessors stay here too — full dependency injection of
settings is a larger change than the env split and is deliberately not
part of it.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

from .core.settings import (
    Config,
    ConfigNotInitialized,
    CrawlerEnv,
    db_name_for,
    default_ai_service_url,
    endpoint_for,
)

__all__ = [
    "Config",
    "ConfigNotInitialized",
    "CrawlerEnv",
    "get_config",
    "init_config",
    "reset_config",
    "settings_from_env",
]

_config: Config | None = None


def settings_from_env() -> Config:
    """Build a Config from os.environ. Does not read .env, does not cache."""
    raw_env = os.getenv("CRAWLER_ENV", "production").lower()
    try:
        env = CrawlerEnv(raw_env)
    except ValueError:
        env = CrawlerEnv.PRODUCTION

    base_db = os.getenv("MONGO_DB_NAME", "skku_notices")

    raw_dept = os.getenv("CRAWL_SOURCE_FILTER", "").strip()
    dept_filter = tuple(d.strip() for d in raw_dept.split(",") if d.strip()) or None

    # Bus lives in its own database, not alongside notices. The name has a
    # working default because it is not a secret and not a gate; whether the
    # bus family runs is decided by the keys below, which have none.
    bus_db = os.getenv("MONGO_DB_NAME_BUS_CAMPUS", "bus_campus")

    return Config(
        env=env,
        mongo_url=os.getenv("MONGO_URL"),
        mongo_db_name=db_name_for(base_db, env),
        log_format=os.getenv("LOG_FORMAT", "json"),
        dept_filter=dept_filter,
        ai_service_url=os.getenv("AI_SERVICE_URL") or default_ai_service_url(env),
        dispatch_url=os.getenv("DISPATCH_URL") or None,
        internal_dispatch_token=os.getenv("INTERNAL_DISPATCH_TOKEN") or None,
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL") or None,
        mongo_bus_db_name=db_name_for(bus_db, env),
        # The whole URL is the credential for this upstream — there is no
        # separate key — so it is read like one and never logged.
        hssc_api_url=endpoint_for(
            env,
            prod=os.getenv("API_HSSC_NEW_PROD") or None,
            dev=os.getenv("API_HSSC_NEW_DEV") or None,
        ),
        seoul_bus_service_key=os.getenv("SEOUL_BUS_SERVICE_KEY") or None,
        naver_api_key_id=os.getenv("NAVER_API_KEY_ID") or None,
        naver_api_key=os.getenv("NAVER_API_KEY") or None,
    )


def init_config(*, force: bool = False) -> Config:
    """Load .env and cache the resulting Config as a singleton.

    Calls ``load_dotenv(override=False)`` internally so that system-level
    environment variables (e.g. Docker ENV) take precedence over ``.env``.
    """
    global _config
    if _config is not None and not force:
        return _config

    load_dotenv()  # override=False by default: system env > .env file

    # No MONGO_URL check here since PR 8. Config loading stops enforcing
    # deployment policy: "no store" is a legitimate configuration now that
    # mongo is an extra, and `notices --json` depends on it. The
    # requirement moved to where a store is actually needed —
    # shared.db.get_client() and wiring.build_runtime(profile=production).
    _config = settings_from_env()
    return _config


def get_config() -> Config:
    """Return the cached config. Raises if init_config() has not run.

    Deliberately NOT lazy: the old fallback made init_config()'s
    SystemExit(1) reachable from any call depth (configure_logging → deep
    library code), which is the mine adr-006/PR 1 removes.
    """
    if _config is None:
        raise ConfigNotInitialized()
    return _config


def reset_config() -> None:
    """Clear cached config singleton. For testing only."""
    global _config
    _config = None
