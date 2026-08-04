"""The 09:00 daily summary — previously untested.

This is the one message an operator reads when nothing is obviously
broken, so the numbers in it are load-bearing: "소스 136개 활성" is what
makes a silent-block incident visible (known-issues §7). It had no
coverage at all while it hardcoded the notices source list; now that what
it reports comes in as probes, the wiring between them is worth pinning.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from skkuverse_crawler.plugins.health.module import (
    CoverageProbe,
    CrawlHealthSummaryModule,
    run_daily_summary,
)


class _Notifier:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def notify(self, content: str) -> bool:
        self.sent.append(content)
        return True


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def __aiter__(self):
        async def gen():
            for doc in self._docs:
                yield doc

        return gen()


class _FakeHealthCollection:
    def __init__(self, docs):
        self._docs = docs
        self.queried_with = None

    def find(self, filter_):
        self.queried_with = filter_
        return _FakeCursor(self._docs)


@pytest.fixture
def health_docs():
    return []


@pytest.fixture
def db(health_docs):
    collection = _FakeHealthCollection(health_docs)
    fake_db = {"crawl_health": collection}
    with patch(
        "skkuverse_crawler.plugins.health.module.get_db",
        AsyncMock(return_value=fake_db),
    ):
        yield collection


def _probe(name, ids, count):
    async def inserted_since(cutoff):
        return count

    return CoverageProbe(
        name=name, enabled_ids=lambda: set(ids), inserted_since=inserted_since
    )


class TestProbeAggregation:
    async def test_no_probes_reports_nothing_rather_than_failing(self, db):
        """A process running only modules that contribute no coverage still
        sends its summary — the plugin line alone is worth having."""
        result = await run_daily_summary(_Notifier(), ())
        assert result["enabled"] == 0
        assert result["inserted24h"] == 0

    async def test_one_probe_supplies_the_counts(self, db):
        result = await run_daily_summary(_Notifier(), (_probe("notices", {"a", "b"}, 7),))
        assert result["enabled"] == 2
        assert result["inserted24h"] == 7

    async def test_two_families_union_their_sources_and_sum_their_inserts(self, db):
        """The reason probes exist: a second module family reports through
        this same message instead of needing its own."""
        result = await run_daily_summary(
            _Notifier(),
            (_probe("notices", {"a", "b"}, 7), _probe("bus", {"hssc"}, 3)),
        )
        assert result["enabled"] == 3
        assert result["inserted24h"] == 10

    async def test_ids_shared_between_families_are_not_double_counted(self, db):
        result = await run_daily_summary(
            _Notifier(), (_probe("x", {"a"}, 1), _probe("y", {"a"}, 1))
        )
        assert result["enabled"] == 1

    async def test_the_cutoff_is_24h_back(self, db):
        seen = {}

        async def capture(cutoff):
            seen["cutoff"] = cutoff
            return 0

        probe = CoverageProbe(name="p", enabled_ids=set, inserted_since=capture)
        await run_daily_summary(_Notifier(), (probe,))
        delta = datetime.now(timezone.utc) - seen["cutoff"]
        assert timedelta(hours=23, minutes=59) < delta < timedelta(hours=24, minutes=1)


class TestFailingSources:
    @pytest.mark.parametrize(
        "health_docs",
        [[{"sourceId": "a", "sourceName": "A", "consecutiveFailures": 5}]],
    )
    async def test_a_failing_enabled_source_is_reported(self, db):
        notifier = _Notifier()
        result = await run_daily_summary(notifier, (_probe("n", {"a"}, 0),))
        assert result["failing"] == 1
        assert "A" in notifier.sent[0]

    @pytest.mark.parametrize(
        "health_docs",
        [[{"sourceId": "retired", "sourceName": "R", "consecutiveFailures": 99}]],
    )
    async def test_a_retired_source_stops_haunting_the_summary(self, db):
        """A source dropped via crawlAvailable=false leaves its crawl_health
        doc behind and can never "recover", because nothing crawls it any
        more. Filtering by the probes' enabled ids is what retires it."""
        result = await run_daily_summary(_Notifier(), (_probe("n", {"a"}, 0),))
        assert result["failing"] == 0

    async def test_only_currently_failing_docs_are_queried(self, db):
        await run_daily_summary(_Notifier(), ())
        assert db.queried_with == {"consecutiveFailures": {"$gt": 0}}


class TestDelivery:
    async def test_the_message_is_sent_and_the_result_says_so(self, db):
        notifier = _Notifier()
        result = await run_daily_summary(notifier, (_probe("n", {"a"}, 4),))
        assert len(notifier.sent) == 1
        assert result["sent"] is True
        assert "일일 요약" in notifier.sent[0]

    async def test_the_summary_does_not_call_the_count_a_notice(self, db):
        """The module is family-agnostic now; the wording has to be too, or
        a bus tick shows up as a "신규 공지"."""
        notifier = _Notifier()
        await run_daily_summary(notifier, (_probe("n", {"a"}, 4),))
        assert "신규 공지" not in notifier.sent[0]


class TestModuleShape:
    def test_it_runs_daily_at_0900(self):
        config = CrawlHealthSummaryModule(_Notifier()).config
        assert config.name == "crawl-health-summary"
        assert config.cron_schedule == "0 9 * * *"

    async def test_run_forwards_the_injected_probes(self, db):
        module = CrawlHealthSummaryModule(_Notifier(), probes=(_probe("n", {"a", "b"}, 9),))
        result = await module.run()
        assert result["enabled"] == 2
        assert result["inserted24h"] == 9

    async def test_probes_default_to_empty_rather_than_to_notices(self, db):
        """Constructing it without probes must not quietly re-acquire the
        notices dependency this change removed."""
        result = await CrawlHealthSummaryModule(_Notifier()).run()
        assert result["enabled"] == 0
