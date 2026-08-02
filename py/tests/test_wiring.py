"""The composition root — assembly-time validation and what it registers.

wiring is where a broken adapter must surface: once per boot, with a
sentence naming the missing methods, instead of an AttributeError three
hours into a crawl (adr-006 결정 ⑦).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from skkuverse_crawler import wiring
from skkuverse_crawler.core.ports import Ports, SeenIndex, Sink
from skkuverse_crawler.wiring import WiringError, build_notices_runtime


class _SinkMissingFlush:
    def __init__(self, collection):
        self.collection = collection

    async def prepare(self, source):
        return None

    async def accept(self, event):
        return None


class TestAssemblyValidation:
    async def test_valid_adapters_assemble(self):
        ports, seen = build_notices_runtime(object())
        assert isinstance(ports, Ports)
        assert isinstance(ports.sink, Sink)
        assert isinstance(seen, SeenIndex)

    async def test_sink_without_flush_is_refused_by_name(self):
        # Patched at its source: wiring imports the adapters inside
        # build_notices_runtime now, so motor stays optional.
        with patch("skkuverse_crawler.plugins.mongo.sink.MongoSink", _SinkMissingFlush):
            with pytest.raises(WiringError) as exc:
                build_notices_runtime(object())
        message = str(exc.value)
        assert "_SinkMissingFlush" in message
        assert "Sink" in message
        assert "prepare/accept/flush" in message

    async def test_seen_index_is_returned_outside_the_bundle(self):
        """It belongs to CrawlMode (Incremental(seen)), not to Ports —
        pinned because putting it back would resurrect the emergent
        incremental-vs-full coupling PR 6 removed."""
        ports, _ = build_notices_runtime(object())
        assert not hasattr(ports, "seen")


class TestNoticesPortsFactory:
    """The production factory itself.

    Everything else injects an already-built bundle, so without this the
    collection name is unchecked: `db["notice"]` would leave the whole
    suite green and write every notice to an empty collection.
    """

    async def test_binds_the_notices_collection(self, mock_db_patch):
        ports, seen = await wiring.notices_ports()
        assert ports.sink._collection is mock_db_patch
        assert ports.work_seed._collection is mock_db_patch
        assert seen._collection is mock_db_patch

    async def test_asks_the_db_for_notices_by_name(self):
        seen_keys: list[str] = []

        class _DB:
            def __getitem__(self, key):
                seen_keys.append(key)
                return object()

        async def fake_get_db():
            return _DB()

        with patch("skkuverse_crawler.shared.db.get_db", side_effect=fake_get_db):
            await wiring.notices_ports()

        assert seen_keys == ["notices"]


class TestPortsLifetime:
    async def test_each_call_builds_a_fresh_bundle(self):
        """Never cache: MongoSink's prepare guard and touch buffer are
        instance state (plan PR 7 ⚠️)."""
        first, first_seen = build_notices_runtime(object())
        second, second_seen = build_notices_runtime(object())
        assert first is not second
        assert first.sink is not second.sink
        assert first.work_seed is not second.work_seed
        assert first_seen is not second_seen


class TestBuildRuntime:
    async def test_registers_every_scheduled_module(self):
        with patch("skkuverse_crawler.core.registry.register") as register:
            modules = wiring.build_runtime()

        names = [m.config.name for m in modules]
        assert names == [
            "notices",
            "notices-update-check",
            "notices-summary",
            "crawl-health-summary",
        ]
        assert register.call_count == len(modules)

    async def test_notices_module_gets_ports_factory_and_health_hook(self):
        with patch("skkuverse_crawler.core.registry.register"):
            notices = wiring.build_runtime()[0]

        assert notices._ports_factory is wiring.notices_ports
        assert notices._on_results is not None


class TestProductionProfileGate:
    """The boot refusal that makes extras safe (plan 위험 ⑤).

    Once "no mongo plugin" is a legitimate state, a production deployment
    that lost MONGO_URL — or an image built without `--extra mongo` —
    would crawl all 136 sources, fetch every detail page, store nothing,
    and log a clean success. Deploy's health check ("container running
    after 10s") would pass it. These tests pin the refusal that turns that
    into a fast, loud, rollback-triggering exit.
    """

    @staticmethod
    def _settings(**overrides):
        from skkuverse_crawler.core.settings import Config, CrawlerEnv

        base = dict(
            env=CrawlerEnv.PRODUCTION,
            mongo_url="mongodb://x/y",
            mongo_db_name="skku_notices",
            log_format="json",
            dept_filter=None,
            ai_service_url="http://ai:4000",
            dispatch_url=None,
            internal_dispatch_token=None,
            discord_webhook_url=None,
        )
        base.update(overrides)
        return Config(**base)

    async def test_production_refuses_when_a_required_plugin_is_not_installed(self):
        real = wiring._installed

        with patch.object(wiring, "_installed", lambda dist: False if dist == "motor" else real(dist)):
            with pytest.raises(wiring.ProfileError) as exc:
                wiring.build_runtime(self._settings())

        message = str(exc.value)
        assert "mongo" in message
        assert "--extra mongo" in message, "the message must say how to fix it"
        assert "store nothing" in message, "the message must say what going ahead would do"

    async def test_production_refuses_when_a_required_plugin_is_unconfigured(self):
        with pytest.raises(wiring.ProfileError, match="not configured"):
            wiring.build_runtime(self._settings(mongo_url=None))

    async def test_development_does_not_refuse(self):
        from skkuverse_crawler.core.settings import CrawlerEnv

        with patch("skkuverse_crawler.core.registry.register"):
            modules = wiring.build_runtime(
                self._settings(env=CrawlerEnv.DEVELOPMENT, mongo_url=None)
            )
        assert modules, "non-production profiles assemble whatever is available"

    async def test_profile_can_be_overridden_independently_of_the_environment(self):
        from skkuverse_crawler.core.settings import CrawlerEnv

        with pytest.raises(wiring.ProfileError):
            wiring.build_runtime(
                self._settings(env=CrawlerEnv.DEVELOPMENT, mongo_url=None),
                profile=CrawlerEnv.PRODUCTION,
            )


class TestActivePlugins:
    def test_derived_from_what_is_installed_and_configured(self):
        settings = TestProductionProfileGate._settings(discord_webhook_url=None)
        active = wiring.active_plugins(settings)

        assert "mongo" in active, "installed and configured"
        assert "discord" not in active, "installed but unconfigured — not active"

    def test_an_uninstalled_plugin_is_not_active(self):
        settings = TestProductionProfileGate._settings()
        real = wiring._installed
        with patch.object(wiring, "_installed", lambda d: False if d == "motor" else real(d)):
            assert "mongo" not in wiring.active_plugins(settings)


class TestRequiredSetsAreDistinct:
    """Installed-vs-configured is the distinction that keeps the gate from
    taking production down over an optional feature."""

    async def test_production_boots_without_a_discord_webhook(self):
        """Alerts unconfigured is a documented, supported state — the boot
        log announces it. Refusing to start would trade a nice-to-have for
        the whole crawler."""
        settings = TestProductionProfileGate._settings(discord_webhook_url=None)
        with patch("skkuverse_crawler.core.registry.register"):
            modules = wiring.build_runtime(settings)
        assert modules

    async def test_production_refuses_when_discord_is_not_installed(self):
        """But build_runtime imports plugins.discord unconditionally, so the
        code being absent must fail at the gate with a message, not three
        lines later on an ImportError."""
        real = wiring._installed
        with patch.object(
            wiring, "_installed", lambda d: False if d == "tenacity" else real(d)
        ):
            with pytest.raises(wiring.ProfileError) as exc:
                wiring.build_runtime(TestProductionProfileGate._settings())
        assert "--extra discord" in str(exc.value) or "--extra ai" in str(exc.value)

    def test_only_mongo_must_be_configured(self):
        assert wiring.REQUIRED_CONFIGURED == ("mongo",)
        assert set(wiring.REQUIRED_CONFIGURED) <= set(wiring.REQUIRED_INSTALLED)
