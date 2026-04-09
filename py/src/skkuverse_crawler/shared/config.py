from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from enum import Enum

from dotenv import load_dotenv


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


_config: Config | None = None


def _db_name(base: str, env: CrawlerEnv) -> str:
    if env == CrawlerEnv.TEST:
        return f"{base}_test"
    if env == CrawlerEnv.DEVELOPMENT:
        return f"{base}_dev"
    return base


def load_config() -> Config:
    """Build a Config from os.environ. Does not cache."""
    raw_env = os.getenv("CRAWLER_ENV", "production").lower()
    try:
        env = CrawlerEnv(raw_env)
    except ValueError:
        env = CrawlerEnv.PRODUCTION

    base_db = os.getenv("MONGO_DB_NAME", "skku_notices")

    raw_dept = os.getenv("CRAWL_DEPT_FILTER", "").strip()
    dept_filter = tuple(d.strip() for d in raw_dept.split(",") if d.strip()) or None

    return Config(
        env=env,
        mongo_url=os.getenv("MONGO_URL"),
        mongo_db_name=_db_name(base_db, env),
        log_format=os.getenv("LOG_FORMAT", "json"),
        dept_filter=dept_filter,
    )


def init_config(*, force: bool = False) -> Config:
    """Load .env, validate required vars, and cache as singleton.

    Calls ``load_dotenv(override=False)`` internally so that
    system-level environment variables (e.g. Docker ENV) take
    precedence over ``.env`` file values.
    """
    global _config
    if _config is not None and not force:
        return _config

    load_dotenv()  # override=False by default: system env > .env file

    cfg = load_config()

    missing = [k for k, v in {"MONGO_URL": cfg.mongo_url}.items() if not v]
    if missing and not cfg.is_test:
        print(f"Missing required config: {', '.join(missing)}", file=sys.stderr)
        raise SystemExit(1)

    _config = cfg
    return _config


def get_config() -> Config:
    """Return cached config, initializing lazily if needed."""
    if _config is None:
        return init_config()
    return _config


def reset_config() -> None:
    """Clear cached config singleton. For testing only."""
    global _config
    _config = None
