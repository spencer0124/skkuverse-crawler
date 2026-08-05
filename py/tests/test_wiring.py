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
        # Fully-configured settings, explicitly: the ambient test config has
        # no bus credentials, so both bus families would be skipped and the
        # built list would legitimately be shorter than the table.
        settings = TestProductionProfileGate._settings()
        with patch("skkuverse_crawler.core.registry.register") as register:
            modules = wiring.build_runtime(settings)

        # Derived from the family table, not restated: a hardcoded list here
        # would have to be edited in lockstep with _FAMILIES, and the whole
        # point of the table is that the names live in one place.
        assert [m.config.name for m in modules] == list(wiring.known_module_names())
        assert register.call_count == len(modules)

    async def test_the_table_still_describes_every_family(self):
        """One literal assertion, so a table edit that drops a module is a
        failing test rather than a quietly smaller runtime."""
        assert wiring.known_module_names() == (
            "notices",
            "notices-update-check",
            "notices-summary",
            "crawl-health-summary",
            "bus-hssc",
            "bus-jongro",
            "bus-campus-eta",
        )

    async def test_notices_module_gets_ports_factory_and_health_hook(self):
        with patch("skkuverse_crawler.core.registry.register"):
            notices = wiring.build_runtime()[0]

        assert notices._ports_factory is wiring.notices_ports
        assert notices._on_results is not None


class TestBusFamilies:
    """The second and third families — the reason adr-006 §⑬ gates 1.0 on a
    second module. Assembly, not behaviour; the modules themselves are
    tested in tests/bus/test_module.py."""

    @staticmethod
    def _built(**overrides):
        settings = TestProductionProfileGate._settings(**overrides)
        with patch("skkuverse_crawler.core.registry.register"):
            return {m.config.name: m for m in wiring.build_runtime(settings)}

    async def test_bus_modules_write_shadow_keys(self):
        """Phase 4's whole safety property, asserted where a reviewer of a
        future PR would look before flipping the constant."""
        assert wiring.BUS_SHADOW_WRITES is True
        built = self._built()
        assert all(
            built[name]._shadow_writes
            for name in ("bus-hssc", "bus-jongro", "bus-campus-eta")
        )

    async def test_each_family_gets_its_own_collection(self):
        """campus_eta is not in bus_cache: that collection carries the
        server's 60-second TTL index, and a ten-minute cadence would leave
        the document absent for nine of every ten minutes."""
        built = self._built()
        assert built["bus-hssc"]._sink_factory is wiring.bus_cache_ports
        assert built["bus-jongro"]._sink_factory is wiring.bus_cache_ports
        assert built["bus-campus-eta"]._sink_factory is wiring.campus_eta_ports

    async def test_alert_thresholds_are_scaled_to_the_cadence(self):
        """plugins/health's THRESHOLD of 3 is ninety minutes of the notices
        crawl and thirty SECONDS of the HSSC poller. Left alone it would
        fire on the first flap."""
        built = self._built()
        for name in ("bus-hssc", "bus-jongro", "bus-campus-eta"):
            hook = built[name]._on_results
            interval = built[name].config.interval_seconds
            seconds = hook.keywords["threshold"] * interval
            assert seconds >= 300, f"{name} would alert after {seconds}s"

    async def test_the_two_families_carry_different_labels(self):
        """One webhook, three processes once the containers split — the
        label is what says which one is talking."""
        built = self._built()
        assert built["bus-hssc"]._on_results.keywords["label"] == "bus"
        assert built["bus-campus-eta"]._on_results.keywords["label"] == "bus-eta"

    async def test_a_lapsed_naver_key_does_not_take_the_shuttle_board_down(self):
        """The entire reason for two families rather than one.

        In production an unconfigured SELECTED family is a boot refusal.
        Folded into a single `bus` family, the Phase 5 container's
        `--module bus-hssc,bus-jongro` would select the family that also
        owns campus ETA, and an expired Naver key would stop the shuttle
        board. Split, that selection names only the family it needs.
        """
        settings = TestProductionProfileGate._settings(naver_api_key=None)
        with patch("skkuverse_crawler.core.registry.register"):
            modules = wiring.build_runtime(
                settings, selection=["bus-hssc", "bus-jongro"]
            )
        assert [m.config.name for m in modules] == ["bus-hssc", "bus-jongro"]

    async def test_outside_production_only_the_unconfigured_family_is_skipped(self):
        """The developer without someone else's API key still gets the
        rest — per family, so the missing Naver key costs exactly campus
        ETA."""
        from skkuverse_crawler.core.settings import CrawlerEnv

        built = self._built(env=CrawlerEnv.DEVELOPMENT, naver_api_key=None)
        assert "bus-campus-eta" not in built
        assert {"bus-hssc", "bus-jongro", "notices"} <= set(built)

    async def test_selecting_the_bus_modules_builds_nothing_else(self):
        """The Phase 5 container split, which is why selection lives in
        build_runtime: an unselected family is never built, so a bus-only
        process boots without notices' configuration and vice versa."""
        settings = TestProductionProfileGate._settings()
        with patch("skkuverse_crawler.core.registry.register"):
            modules = wiring.build_runtime(
                settings, selection=["bus-hssc", "bus-jongro"]
            )
        assert [m.config.name for m in modules] == ["bus-hssc", "bus-jongro"]

    async def test_a_notices_only_process_needs_no_bus_credentials(self):
        settings = TestProductionProfileGate._settings(
            mongo_bus_db_name=None,
            hssc_api_url=None,
            seoul_bus_service_key=None,
            naver_api_key_id=None,
            naver_api_key=None,
        )
        with patch("skkuverse_crawler.core.registry.register"):
            modules = wiring.build_runtime(settings, selection=["notices"])
        assert [m.config.name for m in modules] == ["notices"]


class TestBusSinkFactories:
    """Where the documents actually land.

    Everything else injects an already-built sink, so without these the
    database and collection names are unchecked — and both failures are
    silent: the wrong collection is created on first write, and the wrong
    database is the notices one, where nothing reads bus_cache and nothing
    complains.
    """

    @staticmethod
    def _spy():
        asked: list[tuple[str | None, str]] = []

        class _DB:
            def __init__(self, name):
                self._name = name

            def __getitem__(self, collection):
                asked.append((self._name, collection))
                return object()

        async def fake_get_db(name=None):
            return _DB(name)

        return asked, fake_get_db

    async def test_bus_cache_goes_to_the_bus_database(self):
        asked, fake_get_db = self._spy()
        with patch("skkuverse_crawler.shared.db.get_db", side_effect=fake_get_db):
            with patch("skkuverse_crawler.env.get_config") as get_config:
                get_config.return_value = TestProductionProfileGate._settings()
                sink = await wiring.bus_cache_ports()

        assert asked == [("skkubus", "bus_cache")]
        assert isinstance(sink, Sink)

    async def test_campus_eta_goes_to_its_own_collection(self):
        asked, fake_get_db = self._spy()
        with patch("skkuverse_crawler.shared.db.get_db", side_effect=fake_get_db):
            with patch("skkuverse_crawler.env.get_config") as get_config:
                get_config.return_value = TestProductionProfileGate._settings()
                await wiring.campus_eta_ports()

        assert asked == [("skkubus", "campus_eta")]

    async def test_a_missing_bus_database_is_refused_not_defaulted(self):
        """`get_db(None)` falls back to the NOTICES database. Without this
        guard a missing MONGO_DB_NAME_BUS_CAMPUS would put bus_cache
        documents into skku_notices — no error, nothing reading them."""
        _asked, fake_get_db = self._spy()
        with patch("skkuverse_crawler.shared.db.get_db", side_effect=fake_get_db):
            with patch("skkuverse_crawler.env.get_config") as get_config:
                get_config.return_value = TestProductionProfileGate._settings(
                    mongo_bus_db_name=None
                )
                with pytest.raises(WiringError, match="MONGO_DB_NAME_BUS_CAMPUS"):
                    await wiring.bus_cache_ports()

    async def test_a_sink_missing_flush_is_refused_by_name(self):
        class _NoFlush:
            def __init__(self, collection):
                pass

            async def prepare(self, source):
                return None

            async def accept(self, event):
                return None

        with patch(
            "skkuverse_crawler.plugins.mongo.snapshot.SnapshotSink", _NoFlush
        ):
            with pytest.raises(WiringError, match="prepare/accept/flush"):
                wiring.build_bus_runtime(object())


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
            # The bus families' credentials. Present by default because an
            # unconfigured SELECTED family is a production refusal: without
            # these, every unselected-scope build_runtime() call in this
            # file would raise ProfileError before reaching what it tests.
            # The service key has to satisfy the URL-encoding pattern —
            # BusJongroModule validates it at construction.
            mongo_bus_db_name="skkubus",
            hssc_api_url="https://hssc.example/api",
            seoul_bus_service_key="test-service-key",
            naver_api_key_id="key-id",
            naver_api_key="key",
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


class TestModuleSelection:
    """Which modules this process runs.

    Selection lives in build_runtime rather than the scheduler so that an
    unselected family is never built — that is what lets a notices-only
    container boot without the bus family's credentials, and it means a
    typo cannot produce a healthy container running nothing.
    """

    async def test_no_selection_means_everything(self):
        settings = TestProductionProfileGate._settings()
        with patch("skkuverse_crawler.core.registry.register"):
            modules = wiring.build_runtime(settings)
        assert len(modules) == len(wiring.known_module_names())

    async def test_a_subset_returns_only_those_modules(self):
        with patch("skkuverse_crawler.core.registry.register"):
            modules = wiring.build_runtime(selection=["notices", "notices-summary"])
        assert [m.config.name for m in modules] == ["notices", "notices-summary"]

    async def test_whitespace_around_names_is_tolerated(self):
        """`--module notices, notices-summary` is a reasonable thing to type."""
        with patch("skkuverse_crawler.core.registry.register"):
            modules = wiring.build_runtime(selection=[" notices ", " notices-summary"])
        assert [m.config.name for m in modules] == ["notices", "notices-summary"]

    async def test_an_unknown_name_raises_and_lists_the_valid_ones(self):
        """The old filter matched silently: `--module notice` scheduled zero
        jobs and the container sat there healthy and idle."""
        with pytest.raises(wiring.UnknownModuleError) as exc:
            wiring.build_runtime(selection=["notice"])
        assert "notice" in str(exc.value)
        assert "notices-update-check" in str(exc.value)

    async def test_one_bad_name_among_good_ones_still_raises(self):
        with pytest.raises(wiring.UnknownModuleError, match="typo"):
            wiring.build_runtime(selection=["notices", "typo"])

    async def test_an_empty_selection_raises_rather_than_running_nothing(self):
        """`--module ""` and `--module ,,` both land here. Running zero
        modules is never what someone meant by naming some."""
        with pytest.raises(wiring.UnknownModuleError, match="no modules selected"):
            wiring.build_runtime(selection=["", "  "])


class TestFamilyConfigGate:
    """A family this process was asked to run but cannot.

    Distinct from the plugin gate: that one asks "is the code installed",
    this one asks "was this family given what it needs". Keyed on the
    SELECTION, not on which variables happen to be set — otherwise a
    notices-only container would refuse to boot over absent bus keys.
    """

    @staticmethod
    def _family_needing(attr: str):
        return wiring.ModuleFamily(
            name="demo",
            module_names=("demo-module",),
            requires=(attr,),
            build=lambda settings, notifier: (_DemoModule(),),
        )

    async def test_production_refuses_when_a_selected_family_is_unconfigured(self):
        family = self._family_needing("seoul_bus_service_key")
        settings = TestProductionProfileGate._settings(seoul_bus_service_key=None)
        with patch.object(wiring, "_FAMILIES", (family,)):
            with pytest.raises(wiring.ProfileError) as exc:
                wiring.build_runtime(settings, selection=["demo-module"])
        assert "demo" in str(exc.value)
        assert "seoul_bus_service_key" in str(exc.value)

    async def test_production_boots_when_the_unconfigured_family_is_not_selected(self):
        """The split-container case, and the reason the gate reads the
        selection: the notices process has no bus credentials and must not
        care that the bus family would fail."""
        settings = TestProductionProfileGate._settings(seoul_bus_service_key=None)
        families = (wiring._FAMILIES[0], self._family_needing("seoul_bus_service_key"))
        with patch.object(wiring, "_FAMILIES", families):
            with patch("skkuverse_crawler.core.registry.register"):
                modules = wiring.build_runtime(settings, selection=["notices"])
        assert [m.config.name for m in modules] == ["notices"]

    async def test_outside_production_the_family_is_skipped_not_refused(self):
        """A developer without a third party's API key still gets the rest
        of the crawler."""
        from skkuverse_crawler.core.settings import CrawlerEnv

        settings = TestProductionProfileGate._settings(
            env=CrawlerEnv.DEVELOPMENT, seoul_bus_service_key=None
        )
        families = (wiring._FAMILIES[0], self._family_needing("seoul_bus_service_key"))
        with patch.object(wiring, "_FAMILIES", families):
            with patch("skkuverse_crawler.core.registry.register"):
                modules = wiring.build_runtime(settings)
        names = [m.config.name for m in modules]
        assert "demo-module" not in names
        assert "notices" in names

    async def test_a_configured_family_is_built(self):
        settings = TestProductionProfileGate._settings(seoul_bus_service_key="k")
        with patch.object(wiring, "_FAMILIES", (self._family_needing("seoul_bus_service_key"),)):
            with patch("skkuverse_crawler.core.registry.register"):
                modules = wiring.build_runtime(settings, selection=["demo-module"])
        assert [m.config.name for m in modules] == ["demo-module"]


class TestDeclarationDrift:
    """The family table names modules before anything is imported, because
    the gate has to answer "can this run" without importing the plugins it
    is about to say are missing. That is a second source of truth, so it is
    checked against reality on every assembly."""

    async def test_a_builder_returning_the_wrong_modules_is_a_wiring_error(self):
        lying = wiring.ModuleFamily(
            name="demo",
            module_names=("declared-name",),
            requires=(),
            build=lambda settings, notifier: (_DemoModule(),),  # returns "demo-module"
        )
        with patch.object(wiring, "_FAMILIES", (lying,)):
            with pytest.raises(wiring.WiringError) as exc:
                wiring.build_runtime(TestProductionProfileGate._settings())
        assert "declared-name" in str(exc.value)
        assert "demo-module" in str(exc.value)


class _DemoModule:
    @property
    def config(self):
        from skkuverse_crawler.core.module import ModuleConfig

        return ModuleConfig(name="demo-module", cron_schedule="0 * * * *")

    async def run(self, **kwargs):
        return {}

    async def shutdown(self) -> None:
        return None


class TestNothingToRunIsRefused:
    """The healthy-and-idle container, reached through the config door.

    UnknownModuleError closes the name door. This closes the other one: if
    every selected family is skipped for missing config, run_scheduler
    would add zero jobs and block on the signal forever. The skip's own
    justification ("a developer still gets the rest of the crawler") does
    not apply when the selection WAS that family — there is no rest.
    """

    async def test_refused_even_outside_production(self):
        from skkuverse_crawler.core.settings import CrawlerEnv

        family = TestFamilyConfigGate._family_needing("seoul_bus_service_key")
        settings = TestProductionProfileGate._settings(
            env=CrawlerEnv.DEVELOPMENT, seoul_bus_service_key=None
        )
        with patch.object(wiring, "_FAMILIES", (family,)):
            with pytest.raises(wiring.ProfileError, match="nothing to run"):
                wiring.build_runtime(settings, selection=["demo-module"])

    async def test_a_partially_configured_selection_still_runs(self):
        """Only the all-skipped case is fatal."""
        from skkuverse_crawler.core.settings import CrawlerEnv

        families = (
            wiring._FAMILIES[0],
            TestFamilyConfigGate._family_needing("seoul_bus_service_key"),
        )
        settings = TestProductionProfileGate._settings(
            env=CrawlerEnv.DEVELOPMENT, seoul_bus_service_key=None
        )
        with patch.object(wiring, "_FAMILIES", families):
            with patch("skkuverse_crawler.core.registry.register"):
                modules = wiring.build_runtime(settings)
        names = [m.config.name for m in modules]
        assert "demo-module" not in names
        assert names == list(wiring._FAMILIES[0].module_names)


class TestFamilyTableIsChecked:
    async def test_a_name_claimed_by_two_families_is_refused(self):
        """registry keys on the name and would silently drop one; the
        scheduler would then raise ConflictingIdError at start, after the
        loss already happened."""
        twin = wiring.ModuleFamily(
            name="twin", module_names=("notices",), requires=(), build=lambda s, n: ()
        )
        with patch.object(wiring, "_FAMILIES", wiring._FAMILIES + (twin,)):
            with pytest.raises(wiring.WiringError, match="more than one family"):
                wiring.known_module_names()

    async def test_requires_naming_a_nonexistent_setting_is_a_typo_not_a_gap(self):
        """getattr(..., None) would make a typo in _FAMILIES look exactly
        like a deployment that forgot a variable: production refuses citing
        an attribute that does not exist, everywhere else silently skips."""
        typo = wiring.ModuleFamily(
            name="demo",
            module_names=("demo-module",),
            requires=("seoul_bus_servce_key",),  # missing 'i'
            build=lambda s, n: (_DemoModule(),),
        )
        with patch.object(wiring, "_FAMILIES", (typo,)):
            with pytest.raises(wiring.WiringError, match="does not define"):
                wiring.build_runtime(TestProductionProfileGate._settings())

    async def test_the_drift_check_tolerates_reordering(self):
        """Order carries no meaning downstream, so a reshuffle must not
        fail the boot with a message listing the same names twice."""
        reordered = wiring.ModuleFamily(
            name="notices",
            module_names=(
                "notices-summary",
                "notices",
                "crawl-health-summary",
                "notices-update-check",
            ),
            requires=(),
            build=wiring._build_notices,
        )
        with patch.object(wiring, "_FAMILIES", (reordered,)):
            with patch("skkuverse_crawler.core.registry.register"):
                modules = wiring.build_runtime()
        assert len(modules) == 4
