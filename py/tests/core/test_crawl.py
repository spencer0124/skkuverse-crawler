from __future__ import annotations

import dataclasses

import pytest

from skkuverse_crawler.core.crawl import CrawlMode, FullSweep, Incremental


class _StubSeen:
    async def lookup(self, source_id, article_nos):
        return {}


def test_full_sweep_instances_are_equal():
    assert FullSweep() == FullSweep()


def test_incremental_requires_and_holds_seen():
    stub = _StubSeen()
    assert Incremental(seen=stub).seen is stub
    with pytest.raises(TypeError):
        Incremental()  # type: ignore[call-arg]


def test_modes_are_frozen():
    mode = Incremental(seen=_StubSeen())
    with pytest.raises(dataclasses.FrozenInstanceError):
        mode.seen = _StubSeen()  # type: ignore[misc]


def test_crawl_mode_union_supports_isinstance():
    assert isinstance(FullSweep(), CrawlMode)
    assert isinstance(Incremental(seen=_StubSeen()), CrawlMode)
    assert not isinstance(object(), CrawlMode)


def test_incremental_equality_is_seen_identity_based():
    stub = _StubSeen()
    assert Incremental(seen=stub) == Incremental(seen=stub)
    assert Incremental(seen=stub) != Incremental(seen=_StubSeen())