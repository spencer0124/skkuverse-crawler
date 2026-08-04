"""The sink conformance suite, shipped rather than described.

A written-down contract that nobody can execute is a wish. This module is
the executable form: a third party writes a ``Sink``, calls
``assert_sink_contract`` on it, and finds out whether it satisfies what
``core/runner.py`` assumes — before a crawl finds out for them.

Shipped in the base package on purpose. Putting it in ``tests/`` would
mean the guarantee only exists for people with a checkout of this repo,
which is precisely the audience that does not need it.

Stdlib only, and pytest-free: ``pip install skkuverse-crawler`` must be
enough to run it, and the base package has no test dependency. Failures
are ``AssertionError`` with a message naming the rule, so pytest, unittest
and a bare script all report something useful.

What it cannot check, and the guide says so instead:

- **flush must not swallow exceptions.** A failing flush has to propagate
  and drop the source (adr-006 §⑪); a sink that catches its own write
  errors looks identical from out here.
- **do not buffer the events themselves.** ``ItemCrawled`` references an
  item that can hold 5MB of cleaned HTML; keeping the event alive keeps
  that alive. Extract the fields you need, the way ``MongoSink._touches``
  does. Only a memory profile would see this.
- **build a sink per run.** Instance state (a prepared-once guard, a touch
  buffer) makes a reused sink skip setup on the second run and leak
  buffered work from a failed flush into the next one.
"""

from __future__ import annotations

from dataclasses import dataclass

from .events import (
    BatchCompleted,
    ContentRefreshed,
    CrawlEvent,
    ItemCrawled,
    ItemFailed,
    ItemSkipped,
    ItemUnchanged,
    ListFetchFailed,
    SourceFinished,
    SourceStarted,
)
from .ports import DetailRef, Outcome, Sink, SourceSpec

__all__ = ["assert_sink_contract"]

# Distinctive enough that if it ever reaches a real store, the row says
# where it came from.
CONTRACT_SOURCE_ID = "__contract_test__"


@dataclass(frozen=True)
class _UnknownFutureEvent(CrawlEvent):
    """An event type from a future minor release.

    The tolerant-reader rule exists so that adding one of these is not a
    breaking change; this is the only way to test it from the present.
    """

    payload: str = "surprise"


def _require(condition: bool, message: str) -> None:
    # Not `assert`: python -O strips assert statements, and a conformance
    # suite that silently passes under -O is worse than none.
    if not condition:
        raise AssertionError(message)


def _non_writing_events() -> list[CrawlEvent]:
    """Events a correct sink stores nothing for.

    The progress tier is here in full, plus the two result-tier events
    that report an item the crawl did NOT store (a failure and a skip).
    Calling accept with these is safe against a live sink.
    """
    return [
        SourceStarted(source_id=CONTRACT_SOURCE_ID, source_name="contract test"),
        BatchCompleted(source_id=CONTRACT_SOURCE_ID, index=0),
        ListFetchFailed(source_id=CONTRACT_SOURCE_ID, page=3, error="contract test"),
        SourceFinished(
            source_id=CONTRACT_SOURCE_ID,
            stopped_by="empty_page",
            source_down=False,
            last_error="",
        ),
        ItemFailed(source_id=CONTRACT_SOURCE_ID, article_no=1, error="contract test"),
        ItemSkipped(source_id=CONTRACT_SOURCE_ID, article_no=2, reason="below_floor"),
        _UnknownFutureEvent(source_id=CONTRACT_SOURCE_ID),
    ]


async def assert_sink_contract(
    sink: Sink,
    *,
    sample: ItemCrawled | None = None,
    sample_article_no: int | None = None,
) -> None:
    """Check ``sink`` against the contract ``core.runner.run_events`` relies on.

    Raises ``AssertionError`` naming the rule that failed; returns None on
    success.

    ``sample`` does double duty, and both halves point the same way:

    1. It is the only way to exercise the write-bearing tier. ``core``
       cannot build an ``ItemCrawled`` itself — the payload belongs to the
       module that owns the content, and core does not import modules. The
       caller supplies one.
    2. Passing it is therefore also the consent to write. **Without
       ``sample`` this function stores no items**, so it is safe to run
       against a sink pointed at a real store. With it, expect writes:
       give it a throwaway store, a fake collection, or an in-memory
       stream.

    ``sample_article_no`` is required alongside ``sample`` and must be the
    identity of the item inside it. The follow-up events this suite sends
    (``ItemUnchanged``, ``ContentRefreshed``) have to target the same item,
    or a batching sink's touch and the backfill update land on a document
    that does not exist and the suite silently checks nothing. Core cannot
    read it off ``sample.item`` — that field is deliberately untyped so
    that core stays out of any module's schema — so the caller states it.

    "Stores no items" is the precise claim, not "touches nothing":
    ``prepare`` is still called, and a sink's prepare is its own
    idempotent setup — ``MongoSink`` creates its indexes there. That is
    what prepare is *for*, so a sink whose prepare is unsafe to call is
    already broken in a way this suite is right to surface.

    Example::

        from skkuverse_crawler.core.testing import assert_sink_contract

        async def test_my_sink():
            await assert_sink_contract(
                MySink(throwaway_store),
                sample=an_item_crawled,
                sample_article_no=4242,
            )
    """
    name = type(sink).__name__

    # 1. Shape. runtime_checkable sees method NAMES only, which is exactly
    #    the failure worth catching early: a missing flush would otherwise
    #    surface as an AttributeError hours into a crawl.
    _require(
        isinstance(sink, Sink),
        f"{name} does not satisfy the Sink protocol "
        f"(needs async prepare/accept/flush)",
    )

    # 2. prepare is setup, and setup must survive being called. Its return
    #    value is NOT checked: run_events never reads it, so a sink that
    #    returns something from prepare breaks nothing, and asserting on it
    #    would be inventing a rule the runner does not have.
    await sink.prepare(SourceSpec(source_id=CONTRACT_SOURCE_ID, name="contract"))

    # 3. Nothing was written, so there is nothing to report — including for
    #    the event type this codebase has never heard of. That last one is
    #    the tolerant-reader rule, and it is what lets the progress tier
    #    grow in a minor release without breaking every third-party sink.
    for event in _non_writing_events():
        outcome = await sink.accept(event)
        _require(
            outcome is None,
            f"{name}.accept returned {outcome!r} for "
            f"{type(event).__name__}, expected None — that event carries no write",
        )

    # 4. An empty flush is a no-op, not an error. The runner calls flush on
    #    every BatchCompleted, including pages where nothing was buffered —
    #    a sink that assumes a non-empty buffer here dies on the first
    #    all-known page. The return value is unchecked, same as prepare.
    await sink.flush()

    if sample is None:
        return

    _require(
        sample_article_no is not None,
        "sample was given without sample_article_no — the write tier needs the "
        "item's identity to aim its follow-up events, and core will not read it "
        "off sample.item",
    )
    assert sample_article_no is not None  # narrowing for mypy; _require raised
    await _assert_write_tier(sink, sample, sample_article_no, name)


async def _assert_write_tier(
    sink: Sink, sample: ItemCrawled, article_no: int, name: str
) -> None:
    """The half that stores things. Reached only when a caller passed a sample."""
    _require(
        isinstance(sample, ItemCrawled),
        f"sample must be an ItemCrawled, got {type(sample).__name__}",
    )

    # A new item. The return value is not decoration: run_events reads it
    # to decide inserted-vs-updated, and None is read as INSERTED.
    outcome = await sink.accept(sample)
    _require(
        outcome is None or isinstance(outcome, Outcome),
        f"{name}.accept returned {outcome!r} for ItemCrawled — "
        f"expected an Outcome, or None to mean INSERTED",
    )

    # A known-but-unmodified item. Sinks usually batch these and write on
    # flush, so the return is None even though a write is pending.
    unchanged = await sink.accept(
        ItemUnchanged(
            source_id=sample.source_id,
            article_no=article_no,
            fields={"views": 1},
        )
    )
    _require(
        unchanged is None,
        f"{name}.accept returned {unchanged!r} for ItemUnchanged, expected None",
    )

    # Backfilled content for an item stored earlier. Deliberately not the
    # upsert path: the field list is explicit and no history is recorded.
    refreshed = await sink.accept(
        ContentRefreshed(
            source_id=sample.source_id,
            ref=DetailRef(article_no=article_no, detail_path=""),
            fields={"contentText": "contract test"},
        )
    )
    _require(
        refreshed is None or isinstance(refreshed, Outcome),
        f"{name}.accept returned {refreshed!r} for ContentRefreshed — "
        f"expected an Outcome or None",
    )

    # Flush with something buffered — the path the empty flush above could
    # not reach, and where a batching sink actually writes.
    await sink.flush()
