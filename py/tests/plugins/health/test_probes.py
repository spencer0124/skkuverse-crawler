"""The concrete probes — what each family claims to be crawling.

Small surface, but one with a silent failure behind it:
``run_daily_summary`` keeps only the failing sources whose id some probe
claims. A family whose probe under-reports is not noisy, it is quiet —
its outages are filtered out of the one message anybody reads.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from skkuverse_crawler.modules.bus.sources import BusSource
from skkuverse_crawler.plugins.health.module import run_daily_summary
from skkuverse_crawler.plugins.health.probes import bus_probe


class TestBusProbe:
    def test_it_claims_every_bus_module(self):
        """Derived from the enum rather than restated. A fourth poller
        added to BusSource and forgotten here would be invisible in the
        daily summary for exactly as long as nobody noticed."""
        assert bus_probe().enabled_ids() == {s.value for s in BusSource}

    def test_the_ids_are_the_module_names(self):
        """crawl_health keys on SourceResult.source_id, which the bus
        modules set from the same enum value they take their ModuleConfig
        name from. If these drifted apart the probe would claim ids no
        health document ever carries."""
        assert bus_probe().enabled_ids() == {
            "bus-hssc",
            "bus-jongro",
            "bus-campus-eta",
        }

    def test_it_reports_no_intake_count(self):
        """Snapshot documents are upserted under a constant `_id` forever,
        so "created in the last 24 hours" has no answer. None, not zero —
        zero would be summed into the message as a measurement."""
        assert bus_probe().inserted_since is None

    def test_it_needs_no_database(self):
        """It has to be installable in a notices-only container, which has
        no bus configuration at all — that is what lets one process report
        on a poller it does not run. `enabled_ids` is called synchronously
        from `run_daily_summary`, so a probe that reached for a connection
        could not even await it."""
        with patch(
            "skkuverse_crawler.shared.db.get_client",
            side_effect=AssertionError("bus_probe touched the database"),
        ):
            assert bus_probe().enabled_ids()
        assert not inspect.iscoroutinefunction(bus_probe().enabled_ids)


class TestTheSummaryHoleThisCloses:
    """Without a bus probe the daily summary would drop bus outages.

    `run_daily_summary` keeps only the failing sources whose id some probe
    claims — a filter that exists so retired notices sources stop haunting
    the message. A second family that does not claim its ids inherits that
    filter as a silence.
    """

    async def test_a_failing_bus_poller_survives_the_enabled_ids_filter(self):
        docs = [
            {"sourceId": "bus-hssc", "sourceName": "HSSC 셔틀", "consecutiveFailures": 42}
        ]

        class _Cursor:
            def __init__(self, items):
                self._items = items

            def __aiter__(self):
                async def gen():
                    for item in self._items:
                        yield item

                return gen()

        class _Collection:
            def find(self, *_args, **_kwargs):
                return _Cursor(docs)

        notifier = SimpleNamespace(notify=AsyncMock(return_value=True))
        with patch(
            "skkuverse_crawler.plugins.health.module.get_db",
            AsyncMock(return_value={"crawl_health": _Collection()}),
        ):
            with_probe = await run_daily_summary(notifier, (bus_probe(),))
            without_probe = await run_daily_summary(notifier, ())

        assert with_probe["failing"] == 1
        assert without_probe["failing"] == 0, (
            "this is the silence the probe exists to prevent"
        )
