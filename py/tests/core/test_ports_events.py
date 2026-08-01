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
    NoticeUnchanged,
)
from skkuverse_crawler.core.ports import (
    DetailRef,
    NullSink,
    NullWorkSeed,
    Outcome,
    Ports,
    SeenRecord,
    Sink,
    SourceSpec,
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
    assert await sink.accept(NoticeUnchanged(source_id="skku-main", article_no=1, views=3)) is None
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
    event = NoticeUnchanged(source_id="s", article_no=1, views=0)
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
