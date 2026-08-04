"""Ports/events unit tests + the sink contract test prototype.

test_sink_tolerates_unknown_events is the seed of the suite third-party
sink authors will run (plan PR 5 checklist): a sink must return None for
any event it does not recognize — the tolerant-reader contract.
"""

from __future__ import annotations

import dataclasses

import pytest

from skkuverse_crawler.core.events import (
    ChangeInfo,
    CrawlEvent,
    ItemUnchanged,
)
from skkuverse_crawler.core.ports import (
    DetailRef,
    Notifier,
    NullSink,
    NullWorkSeed,
    Outcome,
    Ports,
    SeenIndex,
    SeenRecord,
    Sink,
    SourceSpec,
    WorkSeed,
)


@dataclasses.dataclass(frozen=True)
class _UnknownFutureEvent(CrawlEvent):
    """An event type this codebase has never heard of."""

    payload: str = "surprise"


async def test_sink_tolerates_unknown_events():
    sink = NullSink()
    assert await sink.accept(_UnknownFutureEvent(source_id="test")) is None


async def test_null_sink_is_full_noop():
    sink = NullSink()
    assert await sink.prepare(SourceSpec(source_id="skku-main")) is None
    unchanged = ItemUnchanged(source_id="skku-main", article_no=1, fields={"views": 3})
    assert await sink.accept(unchanged) is None
    assert await sink.flush() is None


async def test_null_work_seed_returns_empty():
    assert await NullWorkSeed().pending_refs("skku-main") == ()


def test_null_sink_satisfies_sink_protocol():
    assert isinstance(NullSink(), Sink)


def test_seen_record_content_hash_defaults_to_none():
    rec = SeenRecord(article_no=1, title="t", date="2026-01-01")
    assert rec.content_hash is None


def test_port_dataclasses_are_frozen():
    rec = SeenRecord(article_no=1, title="t", date="2026-01-01")
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.title = "changed"  # type: ignore[misc]
    event = ItemUnchanged(source_id="s", article_no=1, fields={"views": 0})
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.views = 9  # type: ignore[misc]


def test_detail_ref_path_defaults_empty():
    assert DetailRef(article_no=7).detail_path == ""


def test_outcome_values_inherit_legacy_strings():
    assert Outcome.INSERTED.value == "inserted"
    assert Outcome.UPDATED.value == "updated"


def test_ports_defaults_to_null_objects():
    ports = Ports()
    assert isinstance(ports.sink, NullSink)
    assert isinstance(ports.work_seed, NullWorkSeed)


def test_runtime_checkable_ports_accept_conforming_objects():
    # wiring's assembly-time isinstance validation (plan PR 7) relies on
    # these three protocols being runtime_checkable.
    class _Seen:
        async def lookup(self, source_id, article_nos):
            return {}

    class _Seed:
        async def pending_refs(self, source_id):
            return ()

    class _Notifier:
        async def notify(self, content: str) -> bool:
            return True

    assert isinstance(_Seen(), SeenIndex)
    assert isinstance(_Seed(), WorkSeed)
    assert isinstance(_Notifier(), Notifier)


def test_runtime_checkable_ports_reject_missing_methods():
    class _NoFlush:
        async def prepare(self, source):
            return None

        async def accept(self, event):
            return None

    class _NotANotifier:
        async def send(self, content: str) -> bool:
            return True

    assert not isinstance(_NoFlush(), Sink)
    assert not isinstance(_NotANotifier(), Notifier)


def test_change_info_carries_module_side_facts_only():
    info = ChangeInfo(
        old_hash="a",
        new_hash="b",
        old_title="old",
        new_title="new",
        title_changed=True,
        content_changed=True,
    )
    assert not hasattr(info, "detectedAt")
    assert not hasattr(info, "source")
