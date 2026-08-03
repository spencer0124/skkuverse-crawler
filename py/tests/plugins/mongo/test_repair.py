"""Repairing what Tier-2 damaged before it ran the pipeline.

The measurements are not gone: Tier-2 rewrote ``cleanHtml`` without
width/height but never touched ``cleanMarkdown``, so the stale markdown
still carries every ``{WxH}`` it was written with. These tests pin that
the repair reads them back, that it changes nothing on a healthy
document, and that it never writes without ``--apply``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from skkuverse_crawler.modules.notices.normalizer import dimensions_from_markdown
from skkuverse_crawler.modules.notices.stages import (
    REPAIR_PIPELINE,
    rederive_from_clean_html,
)
from skkuverse_crawler.plugins.mongo.repair import repair_lost_dimensions
from tests.support.fake_mongo import FakeCollection

IMG = "https://example.com/poster.png"
# The realistic damaged state, and the two halves matter separately:
# cleanHtml holds the CURRENT body but lost its dimensions (Tier-2 wrote
# it), while cleanMarkdown holds the PREVIOUS body and kept them (Tier-2
# never touched it). So the repair has to take the body from one and the
# measurements from the other.
HEALTHY_HTML = f'<div><p>새 본문</p><img src="{IMG}" width="891" height="1260"></div>'
DAMAGED_HTML = f'<div><p>새 본문</p><img src="{IMG}"></div>'
STALE_MARKDOWN = f"옛 본문\n\n![{{891x1260}}]({IMG})"


def _damaged_doc(**overrides):
    """A notice in the exact state Tier-2 used to leave behind: sanitized
    HTML with the dimensions stripped, markdown that still remembers
    them, and text taken from the strategy rather than the HTML."""
    doc = {
        "articleNo": 1,
        "sourceId": "test-dept",
        "content": DAMAGED_HTML,
        "cleanHtml": DAMAGED_HTML,
        "cleanMarkdown": STALE_MARKDOWN,
        "contentText": "본문",
        "contentHash": "stale-hash",
        "editHistory": [{"source": "tier2"}],
    }
    doc.update(overrides)
    return doc


async def _store(doc) -> FakeCollection:
    collection = FakeCollection()
    await collection.update_one(
        {"articleNo": doc["articleNo"], "sourceId": doc["sourceId"]},
        {"$set": doc},
        upsert=True,
    )
    return collection


async def _run(collection: FakeCollection, **kwargs):
    with patch("skkuverse_crawler.shared.db.get_db", return_value={"notices": collection}):
        return await repair_lost_dimensions(**kwargs)


# ── the repair pipeline itself ────────────────────────────────────────────


def test_the_repair_pipeline_is_the_tail_of_the_real_one():
    """Not a re-implementation: the same stage objects, minus the three
    that need raw detail HTML a stored document does not keep."""
    assert [s.name for s in REPAIR_PIPELINE.stages] == [
        "inject-image-dimensions",
        "size-guard",
        "extract-text",
        "to-markdown",
        "content-hash",
    ]


async def test_rederiving_restores_the_dimension_hint():
    fields = await rederive_from_clean_html(
        DAMAGED_HTML, dimensions=dimensions_from_markdown(STALE_MARKDOWN)
    )

    assert 'width="891"' in fields.cleanHtml
    assert "![{891x1260}" in fields.cleanMarkdown


async def test_rederiving_a_healthy_document_changes_nothing():
    """Idempotence is what lets the driver write only on a real
    difference — without it every run would rewrite every document."""
    first = await rederive_from_clean_html(
        HEALTHY_HTML, dimensions=dimensions_from_markdown(STALE_MARKDOWN)
    )
    second = await rederive_from_clean_html(
        first.cleanHtml, dimensions=dimensions_from_markdown(first.cleanMarkdown)
    )

    assert first == second


async def test_it_never_re_sanitises_the_body():
    """The body comes in already clean and must come out untouched apart
    from injection. Re-running clean_html over stored content is what
    adr-006 §④ forbids — it would rewrite every notice's HTML."""
    fields = await rederive_from_clean_html(HEALTHY_HTML)

    assert fields.cleanHtml == HEALTHY_HTML


# ── the driver ────────────────────────────────────────────────────────────


async def test_a_dry_run_reports_without_writing():
    collection = await _store(_damaged_doc())
    report = await _run(collection)

    assert report.repaired == 1
    assert collection.docs[0]["cleanHtml"] == DAMAGED_HTML, "a dry run wrote to the database"
    assert collection.docs[0]["contentHash"] == "stale-hash"


async def test_apply_restores_every_derived_field():
    collection = await _store(_damaged_doc())
    report = await _run(collection, apply=True)

    stored = collection.docs[0]
    assert report.repaired == 1
    assert 'width="891"' in stored["cleanHtml"]
    assert "![{891x1260}" in stored["cleanMarkdown"]
    assert stored["contentHash"] != "stale-hash"
    # The body catches up and the measurements come back — from two
    # different stored fields.
    assert "새 본문" in stored["cleanMarkdown"]
    assert "옛 본문" not in stored["cleanMarkdown"]
    assert set(report.changed_fields) >= {"cleanHtml", "cleanMarkdown", "contentHash"}


async def test_it_leaves_history_and_crawledAt_alone():
    """The repair fixes derived fields; it did not observe a change at the
    source. Recording either would put a lie in the data."""
    collection = await _store(_damaged_doc(crawledAt="2026-07-01", editCount=3))
    await _run(collection, apply=True)

    stored = collection.docs[0]
    assert stored["crawledAt"] == "2026-07-01"
    assert stored["editCount"] == 3
    assert stored["editHistory"] == [{"source": "tier2"}]


async def test_a_healthy_document_is_not_written():
    """Idempotence at the driver level. Re-running the repair must be
    free, or nobody will dare run it twice."""
    healthy = await rederive_from_clean_html(
        HEALTHY_HTML, dimensions=dimensions_from_markdown(STALE_MARKDOWN)
    )
    collection = await _store(_damaged_doc(
        cleanHtml=healthy.cleanHtml,
        cleanMarkdown=healthy.cleanMarkdown,
        contentText=healthy.contentText,
        contentHash=healthy.contentHash,
    ))
    # From here, and writes only: _store's own upsert is an op, and the
    # scan's find is one too — a total count would be satisfied by either.
    ops_before = len(collection.ops)
    report = await _run(collection, apply=True)

    assert report.repaired == 0
    assert report.already_consistent == 1
    writes = [op for op in collection.ops[ops_before:] if op[0] != "find"]
    assert writes == [], "a consistent document was rewritten"


async def test_images_with_no_stored_measurement_are_counted_not_invented():
    """The stale markdown's URLs no longer appear in the body — the images
    were swapped in the same edit that lost the dimensions. Nothing to
    restore; the next Tier-2 pass measures them for real."""
    other = "https://example.com/replacement.png"
    collection = await _store(_damaged_doc(
        cleanHtml=f'<p>새 본문</p><img src="{other}">',
        cleanMarkdown=f"새 본문\n\n![]({other})",
        contentText="새 본문",
    ))
    report = await _run(collection, apply=True)

    assert report.unmeasurable == 1
    assert 'width=' not in collection.docs[0]["cleanHtml"]


async def test_a_document_with_no_body_is_skipped():
    collection = await _store(_damaged_doc(cleanHtml=None, cleanMarkdown=None))
    report = await _run(collection)

    assert report.skipped_no_content == 1
    assert report.repaired == 0


async def test_only_tier2_touched_documents_are_scanned():
    """A document the crawl alone has written was never damaged, and
    scanning it costs a derivation for nothing."""
    collection = await _store(_damaged_doc(editHistory=[{"source": "tier1"}]))
    report = await _run(collection)

    assert report.scanned == 0


@pytest.mark.parametrize("dept_filter,expected", [(("test-dept",), 1), (("other",), 0)])
async def test_the_source_filter_narrows_the_scan(dept_filter, expected):
    collection = await _store(_damaged_doc())
    report = await _run(collection, dept_filter=dept_filter)

    assert report.scanned == expected
