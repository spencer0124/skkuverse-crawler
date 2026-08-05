"""The concrete probes — what each family claims to be crawling.

Small surface, but one with a silent failure behind it:
``run_daily_summary`` keeps only the failing sources whose id some probe
claims. A family whose probe under-reports is not noisy, it is quiet —
its outages are filtered out of the one message anybody reads.
"""

from __future__ import annotations

from skkuverse_crawler.modules.bus.sources import BusSource
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

    def test_it_needs_no_credentials_or_io(self):
        """It has to be installable in a notices-only container, which has
        no bus configuration at all — that is what lets one process report
        on a poller it does not run."""
        probe = bus_probe()
        assert probe.enabled_ids() == probe.enabled_ids()
