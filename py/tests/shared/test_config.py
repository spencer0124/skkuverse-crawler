from __future__ import annotations

from unittest.mock import patch

import pytest

from skkuverse_crawler.shared.config import (
    Config,
    CrawlerEnv,
    get_config,
    init_config,
    load_config,
    reset_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_fresh(monkeypatch, **env_vars):
    """Set env vars, reset singleton, and return a fresh Config."""
    monkeypatch.setenv("CRAWL_DEPT_FILTER", "")
    for k, v in env_vars.items():
        monkeypatch.setenv(k, v)
    reset_config()
    return init_config(force=True)


# ---------------------------------------------------------------------------
# Environment mode & DB suffix
# ---------------------------------------------------------------------------


class TestEnvironmentModes:
    def test_production_mode(self, monkeypatch):
        cfg = _init_fresh(monkeypatch, CRAWLER_ENV="production", MONGO_URL="mongodb://x")
        assert cfg.env == CrawlerEnv.PRODUCTION
        assert cfg.is_production is True
        assert cfg.is_development is False
        assert cfg.is_test is False
        assert cfg.mongo_db_name == "skku_notices"

    def test_development_mode(self, monkeypatch):
        cfg = _init_fresh(monkeypatch, CRAWLER_ENV="development", MONGO_URL="mongodb://x")
        assert cfg.env == CrawlerEnv.DEVELOPMENT
        assert cfg.is_development is True
        assert cfg.mongo_db_name == "skku_notices_dev"

    def test_test_mode(self, monkeypatch):
        cfg = _init_fresh(monkeypatch, CRAWLER_ENV="test")
        assert cfg.env == CrawlerEnv.TEST
        assert cfg.is_test is True
        assert cfg.mongo_db_name == "skku_notices_test"

    def test_custom_db_name(self, monkeypatch):
        cfg = _init_fresh(
            monkeypatch, CRAWLER_ENV="development",
            MONGO_DB_NAME="my_db", MONGO_URL="mongodb://x",
        )
        assert cfg.mongo_db_name == "my_db_dev"


# ---------------------------------------------------------------------------
# Case-insensitive CRAWLER_ENV
# ---------------------------------------------------------------------------


class TestCaseInsensitive:
    @pytest.mark.parametrize("raw", ["TEST", "Test", "tEsT"])
    def test_case_variants(self, monkeypatch, raw):
        cfg = _init_fresh(monkeypatch, CRAWLER_ENV=raw)
        assert cfg.env == CrawlerEnv.TEST

    def test_unknown_value_defaults_to_production(self, monkeypatch):
        cfg = _init_fresh(monkeypatch, CRAWLER_ENV="staging", MONGO_URL="mongodb://x")
        assert cfg.env == CrawlerEnv.PRODUCTION


# ---------------------------------------------------------------------------
# Mode label
# ---------------------------------------------------------------------------


class TestModeLabel:
    def test_production_label(self, monkeypatch):
        cfg = _init_fresh(monkeypatch, CRAWLER_ENV="production", MONGO_URL="mongodb://x")
        assert cfg.mode_label == "PRODUCTION (prod DB)"

    def test_development_label(self, monkeypatch):
        cfg = _init_fresh(monkeypatch, CRAWLER_ENV="development", MONGO_URL="mongodb://x")
        assert cfg.mode_label == "DEVELOPMENT (dev DB)"

    def test_test_label(self, monkeypatch):
        cfg = _init_fresh(monkeypatch, CRAWLER_ENV="test")
        assert cfg.mode_label == "TEST"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    """Patch load_dotenv so .env file doesn't re-inject MONGO_URL."""

    @patch("skkuverse_crawler.shared.config.load_dotenv")
    def test_missing_mongo_url_exits_in_production(self, _mock_ld, monkeypatch):
        monkeypatch.setenv("CRAWLER_ENV", "production")
        monkeypatch.delenv("MONGO_URL", raising=False)
        reset_config()
        with pytest.raises(SystemExit):
            init_config(force=True)

    @patch("skkuverse_crawler.shared.config.load_dotenv")
    def test_missing_mongo_url_exits_in_development(self, _mock_ld, monkeypatch):
        monkeypatch.setenv("CRAWLER_ENV", "development")
        monkeypatch.delenv("MONGO_URL", raising=False)
        reset_config()
        with pytest.raises(SystemExit):
            init_config(force=True)

    @patch("skkuverse_crawler.shared.config.load_dotenv")
    def test_missing_mongo_url_ok_in_test(self, _mock_ld, monkeypatch):
        monkeypatch.setenv("CRAWLER_ENV", "test")
        monkeypatch.delenv("MONGO_URL", raising=False)
        reset_config()
        cfg = init_config(force=True)
        assert cfg.mongo_url is None


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_default_values(self, monkeypatch):
        monkeypatch.delenv("CRAWLER_ENV", raising=False)
        monkeypatch.delenv("MONGO_DB_NAME", raising=False)
        monkeypatch.delenv("LOG_FORMAT", raising=False)
        monkeypatch.setenv("MONGO_URL", "mongodb://x")
        reset_config()
        cfg = load_config()
        assert cfg.env == CrawlerEnv.PRODUCTION
        assert cfg.mongo_db_name == "skku_notices"
        assert cfg.log_format == "json"


# ---------------------------------------------------------------------------
# Singleton caching & reset
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_config_caches(self, monkeypatch):
        _init_fresh(monkeypatch, CRAWLER_ENV="test")
        a = get_config()
        b = get_config()
        assert a is b

    def test_reset_clears_cache(self, monkeypatch):
        cfg1 = _init_fresh(monkeypatch, CRAWLER_ENV="test")
        reset_config()
        monkeypatch.setenv("CRAWLER_ENV", "development")
        monkeypatch.setenv("MONGO_URL", "mongodb://x")
        cfg2 = init_config(force=True)
        assert cfg1.env != cfg2.env

    def test_force_reinitializes(self, monkeypatch):
        cfg1 = _init_fresh(monkeypatch, CRAWLER_ENV="test")
        monkeypatch.setenv("CRAWLER_ENV", "development")
        monkeypatch.setenv("MONGO_URL", "mongodb://x")
        cfg2 = init_config(force=True)
        assert cfg2.is_development is True


# ---------------------------------------------------------------------------
# Frozen immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_cannot_mutate(self, monkeypatch):
        cfg = _init_fresh(monkeypatch, CRAWLER_ENV="test")
        with pytest.raises(AttributeError):
            cfg.env = CrawlerEnv.PRODUCTION  # type: ignore[misc]
