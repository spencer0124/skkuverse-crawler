from __future__ import annotations

from unittest.mock import patch

import pytest

from skkuverse_crawler.env import (
    ConfigNotInitialized,
    CrawlerEnv,
    get_config,
    init_config,
    settings_from_env,
    reset_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_fresh(monkeypatch, **env_vars):
    """Set env vars, reset singleton, and return a fresh Config."""
    monkeypatch.setenv("CRAWL_SOURCE_FILTER", "")
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
    """Patch load_dotenv so .env file doesn't re-inject MONGO_URL.

    Since PR 8 config loading no longer enforces MONGO_URL in any
    environment: "no store" is a legitimate configuration once mongo is an
    optional dependency, and `notices --json` relies on it. The
    requirement moved to the two places that actually need a store —
    shared.db.get_client() and wiring's production profile gate — each
    with its own test.
    """

    @pytest.mark.parametrize("env_name", ["production", "development", "test"])
    @patch("skkuverse_crawler.env.load_dotenv")
    def test_missing_mongo_url_is_loadable_in_every_environment(
        self, _mock_ld, monkeypatch, env_name
    ):
        monkeypatch.setenv("CRAWLER_ENV", env_name)
        monkeypatch.delenv("MONGO_URL", raising=False)
        reset_config()
        cfg = init_config(force=True)
        assert cfg.mongo_url is None

    @patch("skkuverse_crawler.env.load_dotenv")
    def test_asking_for_a_client_without_mongo_url_raises(self, _mock_ld, monkeypatch):
        """The requirement did not disappear, it moved. Motor does not
        fail on a None URL — it quietly connects to localhost:27017."""
        import asyncio

        from skkuverse_crawler.shared.db import MongoUrlMissing, get_client

        monkeypatch.setenv("CRAWLER_ENV", "production")
        monkeypatch.delenv("MONGO_URL", raising=False)
        reset_config()
        init_config(force=True)
        with pytest.raises(MongoUrlMissing, match="MONGO_URL"):
            asyncio.run(get_client())

    @patch("skkuverse_crawler.env.load_dotenv")
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
        cfg = settings_from_env()
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
        _init_fresh(monkeypatch, CRAWLER_ENV="test")
        monkeypatch.setenv("CRAWLER_ENV", "development")
        monkeypatch.setenv("MONGO_URL", "mongodb://x")
        cfg2 = init_config(force=True)
        assert cfg2.is_development is True

    def test_get_config_without_init_raises(self):
        """PR 1 contract: no lazy fallback. The old behavior silently ran
        init_config(), making its SystemExit reachable from any call depth."""
        reset_config()
        with pytest.raises(ConfigNotInitialized):
            get_config()

    def test_get_config_works_after_explicit_init(self, monkeypatch):
        _init_fresh(monkeypatch, CRAWLER_ENV="test")
        assert get_config().is_test is True


# ---------------------------------------------------------------------------
# Frozen immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_cannot_mutate(self, monkeypatch):
        cfg = _init_fresh(monkeypatch, CRAWLER_ENV="test")
        with pytest.raises(AttributeError):
            cfg.env = CrawlerEnv.PRODUCTION  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Bus family configuration (the module itself lands later)
# ---------------------------------------------------------------------------


class TestBusDatabase:
    """Bus stores in its own database, so the suffixing has to work there too."""

    def test_unset_is_none_rather_than_a_plausible_literal(self, monkeypatch):
        """skkuverse-server requires the same variable with no default and
        fails startup without it. A crawler that invented "bus_campus"
        would write where the server is not reading — no error anywhere,
        the app just serves nothing. So absent reads as absent and the
        family gate refuses."""
        monkeypatch.delenv("MONGO_DB_NAME_BUS_CAMPUS", raising=False)
        cfg = _init_fresh(monkeypatch, CRAWLER_ENV="production")
        assert cfg.mongo_bus_db_name is None

    @pytest.mark.parametrize(
        "crawler_env,expected",
        [
            ("production", "bus_campus"),
            ("development", "bus_campus_dev"),
            ("test", "bus_campus_test"),
        ],
    )
    def test_a_set_name_gets_the_environment_suffix(
        self, monkeypatch, crawler_env, expected
    ):
        """Matches skkuverse-server's devDbName exactly."""
        cfg = _init_fresh(
            monkeypatch,
            CRAWLER_ENV=crawler_env,
            MONGO_DB_NAME_BUS_CAMPUS="bus_campus",
        )
        assert cfg.mongo_bus_db_name == expected

    def test_it_is_not_the_notices_database(self, monkeypatch):
        """The whole reason get_db takes a name. Sharing one would put bus
        cache documents in the collection the server reads notices from."""
        cfg = _init_fresh(
            monkeypatch, CRAWLER_ENV="production", MONGO_DB_NAME_BUS_CAMPUS="bus_campus"
        )
        assert cfg.mongo_bus_db_name != cfg.mongo_db_name


class TestBusSecrets:
    """Absent means absent — the family gate reads these to decide whether
    bus can run at all, so "" must not read as configured."""

    def test_unset_secrets_are_none(self, monkeypatch):
        for var in (
            "SEOUL_BUS_SERVICE_KEY",
            "NAVER_API_KEY_ID",
            "NAVER_API_KEY",
            "API_HSSC_NEW_PROD",
            "API_HSSC_NEW_DEV",
        ):
            monkeypatch.delenv(var, raising=False)
        cfg = _init_fresh(monkeypatch)
        assert cfg.seoul_bus_service_key is None
        assert cfg.naver_api_key_id is None
        assert cfg.naver_api_key is None
        assert cfg.hssc_api_url is None

    def test_empty_string_is_treated_as_unset(self, monkeypatch):
        cfg = _init_fresh(monkeypatch, SEOUL_BUS_SERVICE_KEY="")
        assert cfg.seoul_bus_service_key is None

    def test_a_set_key_survives_verbatim(self, monkeypatch):
        cfg = _init_fresh(monkeypatch, SEOUL_BUS_SERVICE_KEY="abc%2Fdef")
        assert cfg.seoul_bus_service_key == "abc%2Fdef"


class TestHsscEndpointSelection:
    """The whole URL is the credential, and there are two of them."""

    def test_production_takes_prod(self, monkeypatch):
        cfg = _init_fresh(
            monkeypatch,
            CRAWLER_ENV="production",
            API_HSSC_NEW_PROD="https://prod.example/api",
            API_HSSC_NEW_DEV="https://dev.example/api",
        )
        assert cfg.hssc_api_url == "https://prod.example/api"

    def test_production_never_falls_back_to_dev(self, monkeypatch):
        """Pointing the live crawler at a staging upstream is worse than not
        crawling: it would publish staging data as real."""
        monkeypatch.delenv("API_HSSC_NEW_PROD", raising=False)
        cfg = _init_fresh(
            monkeypatch, CRAWLER_ENV="production", API_HSSC_NEW_DEV="https://dev.example/api"
        )
        assert cfg.hssc_api_url is None

    def test_development_prefers_dev(self, monkeypatch):
        cfg = _init_fresh(
            monkeypatch,
            CRAWLER_ENV="development",
            API_HSSC_NEW_PROD="https://prod.example/api",
            API_HSSC_NEW_DEV="https://dev.example/api",
        )
        assert cfg.hssc_api_url == "https://dev.example/api"

    def test_development_falls_back_to_prod(self, monkeypatch):
        """A developer holding only one URL should still be able to run."""
        monkeypatch.delenv("API_HSSC_NEW_DEV", raising=False)
        cfg = _init_fresh(
            monkeypatch, CRAWLER_ENV="development", API_HSSC_NEW_PROD="https://prod.example/api"
        )
        assert cfg.hssc_api_url == "https://prod.example/api"
