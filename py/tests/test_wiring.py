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
        with patch("skkuverse_crawler.wiring.MongoSink", _SinkMissingFlush):
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
