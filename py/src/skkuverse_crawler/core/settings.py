"""The settings value and its vocabulary — no environment access.

Split out of shared/config.py so that the type everything annotates
against lives in core, while the one place that reads ``os.environ``
stays a leaf (``env.py``, adr-006 결정 ①). Importing this module must
never touch the environment or the filesystem; that is what lets a
library caller build a Config literal and skip env entirely.

Infra-free by contract (pinned by tests/structure
test_core_import_is_infra_free).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CrawlerEnv(str, Enum):
    PRODUCTION = "production"
    DEVELOPMENT = "development"
    TEST = "test"


@dataclass(frozen=True)
class Config:
    env: CrawlerEnv
    mongo_url: str | None
    mongo_db_name: str
    log_format: str
    dept_filter: tuple[str, ...] | None
    ai_service_url: str
    # FCM dispatch ping (optional). Both must be set together; either missing
    # disables the ping and the server's safety-net cron drains the queue
    # within 30 min instead. See plan: latency-vs-correctness tradeoff.
    dispatch_url: str | None
    internal_dispatch_token: str | None
    # Crawl-health Discord alerts (optional). Unset → alerts silently skipped;
    # boot log announces the state once.
    discord_webhook_url: str | None
    # ── everything below has a default ────────────────────────────────────
    # New fields MUST be appended with one. Config is frozen and has no
    # defaults above this line, and tests/test_wiring.py builds it from an
    # explicit full kwargs dict — a new required field breaks them all.
    #
    # Bus (module family added later). The database is separate from
    # notices'; the two secrets are what decide whether the family is
    # configured at all. All three URLs/keys are secrets in their entirety
    # and must never be logged.
    mongo_bus_db_name: str = ""
    hssc_api_url: str | None = None
    seoul_bus_service_key: str | None = None
    naver_api_key_id: str | None = None
    naver_api_key: str | None = None

    @property
    def is_production(self) -> bool:
        return self.env == CrawlerEnv.PRODUCTION

    @property
    def is_development(self) -> bool:
        return self.env == CrawlerEnv.DEVELOPMENT

    @property
    def is_test(self) -> bool:
        return self.env == CrawlerEnv.TEST

    @property
    def mode_label(self) -> str:
        if self.is_production:
            base = "PRODUCTION (prod DB)"
        elif self.is_development:
            base = "DEVELOPMENT (dev DB)"
        else:
            base = "TEST"
        if self.dept_filter:
            base += f" [dept_filter: {','.join(self.dept_filter)}]"
        return base


class ConfigNotInitialized(RuntimeError):
    """get_config() was called before init_config().

    Entrypoints (CLI callbacks) must call init_config() explicitly; library
    code may then read the singleton via get_config(). Tests set env vars
    first and call init_config(force=True).
    """

    def __init__(self) -> None:
        super().__init__(
            "config not initialized — call init_config() at your entrypoint "
            "(tests: set env vars, then init_config(force=True))"
        )


def db_name_for(base: str, env: CrawlerEnv) -> str:
    """Environment-suffixed database name. Pure — the env var that feeds
    ``base`` is read in env.py."""
    if env == CrawlerEnv.TEST:
        return f"{base}_test"
    if env == CrawlerEnv.DEVELOPMENT:
        return f"{base}_dev"
    return base


def default_ai_service_url(env: CrawlerEnv) -> str:
    """In production the AI service is a sibling container; elsewhere it is
    whatever the developer runs locally."""
    if env == CrawlerEnv.PRODUCTION:
        return "http://ai:4000"
    return "http://127.0.0.1:4000"


def endpoint_for(env: CrawlerEnv, *, prod: str | None, dev: str | None) -> str | None:
    """Pick between a prod and a non-prod endpoint. Pure — env.py reads the
    two variables, this decides which one wins.

    Production never falls back to the dev endpoint: pointing the live
    crawler at a staging upstream is worse than not crawling. Everywhere
    else prefers dev but falls back to prod, so a developer holding only
    one URL can still run.
    """
    if env == CrawlerEnv.PRODUCTION:
        return prod
    return dev or prod
