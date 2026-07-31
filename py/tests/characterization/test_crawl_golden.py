"""Characterization goldens for the notices crawl (run_crawl level).

Each case snapshots 4 artifacts (ops / state / result / log_events) under
``snapshots/<case>/``. These pin CURRENT behavior — including the two
incident fixes (pinned-row exclusion, floor-break ordering) and the
null-backfill divergence — so the core/plugin refactor (PR 1..9, adr-006)
can prove byte-identity at every step.

Single source per case: run_crawl's Semaphore(5)+gather interleaves DB writes
across concurrent departments, which would make op order nondeterministic.

Routers register ONLY the URLs a case is expected to fetch — an early-stop
regression that fetches page 1 anyway fails loudly on the un-routed URL,
independent of the snapshots.
"""
from __future__ import annotations

import httpx

from tests.characterization import depts
from tests.characterization.harness import FixtureRouter, run_golden, seed
from tests.support.fake_mongo import FakeCollection


def _std_cold_router() -> FixtureRouter:
    router = (
        FixtureRouter()
        .serve(depts.std_list_url(0), "skku_standard/list_p0.html")
        .serve(depts.std_list_url(1), "skku_standard/list_p1.html")
        .serve(depts.std_list_url(2), "skku_standard/empty.html")
    )
    for article_no in (100, 101, 102, 103, 104, 105):
        router.serve(
            depts.std_detail_url(article_no), f"skku_standard/detail_{article_no}.html"
        )
    return router


async def test_std_three_rounds():
    """cold → warm-unchanged → warm-title-tampered on ONE collection.

    Round 2 is the highest-value golden in the plan: all_known first-page
    early-stop + has_changed()→False + exactly one bulk_touch per page —
    the path with zero coverage before this suite (위험 ②).
    """
    collection = FakeCollection()

    run1 = await run_golden(depts.SKKU_STD_DEPT, _std_cold_router(), collection=collection)
    run1.snapshot_all("std_three_rounds", "round1_cold")

    # Warm, unchanged: only page 0 may be fetched (all_known_first_page break) —
    # no detail URLs are routed, so any detail fetch fails loudly.
    warm_router = FixtureRouter().serve(depts.std_list_url(0), "skku_standard/list_p0.html")
    run2 = await run_golden(depts.SKKU_STD_DEPT, warm_router, collection=collection)
    run2.snapshot_all("std_three_rounds", "round2_warm")

    # 위험 ② direct assertion, independent of snapshot review: the unchanged
    # page produces EXACTLY one bulk_write carrying all 4 rows' touches.
    bulk_ops = [op for op in run2.ops_delta() if op[0] == "bulk_write"]
    assert len(bulk_ops) == 1
    assert len(bulk_ops[0][1]["ops"]) == 4

    # Warm, one title tampered: only article 101 gets a detail re-fetch.
    tampered_router = (
        FixtureRouter()
        .serve(depts.std_list_url(0), "skku_standard/list_p0_tampered.html")
        .serve(depts.std_detail_url(101), "skku_standard/detail_101.html")
    )
    run3 = await run_golden(depts.SKKU_STD_DEPT, tampered_router, collection=collection)
    run3.snapshot_all("std_three_rounds", "round3_tampered")


async def test_std_floor_break_page1():
    """Page ≥1 entirely below SERVICE_START_DATE stops BEFORE processing —
    no detail fetch, no meta lookup for that page (no routes for 90/91)."""
    router = (
        FixtureRouter()
        .serve(depts.std_list_url(0), "skku_standard/list_p0.html")
        .serve(depts.std_list_url(1), "skku_standard/list_floor_p1.html")
    )
    for article_no in (100, 101, 102, 103):
        router.serve(
            depts.std_detail_url(article_no), f"skku_standard/detail_{article_no}.html"
        )
    run = await run_golden(depts.SKKU_STD_DEPT, router)
    run.snapshot_all("std_floor_page1")


async def test_std_floor_break_page0_processes_first():
    """Page 0 below floor is processed BEFORE breaking — the pinned row
    (recent date, only visible here) must be crawled; regular below-floor
    rows are date-skipped (the incident-fix ordering, 위험 ③)."""
    router = (
        FixtureRouter()
        .serve(depts.std_list_url(0), "skku_standard/list_floor_p0.html")
        .serve(depts.std_detail_url(100), "skku_standard/detail_100.html")
    )
    run = await run_golden(depts.SKKU_STD_DEPT, router)
    run.snapshot_all("std_floor_page0")


async def test_std_pinned_only_page_stops_all_known():
    """A page ≥1 holding only pinned rows: should_continue's all([]) → True →
    all_known break without processing (no re-touch of the pinned row)."""
    router = (
        FixtureRouter()
        .serve(depts.std_list_url(0), "skku_standard/list_p0.html")
        .serve(depts.std_list_url(1), "skku_standard/list_pinned_only.html")
    )
    for article_no in (100, 101, 102, 103):
        router.serve(
            depts.std_detail_url(article_no), f"skku_standard/detail_{article_no}.html"
        )
    run = await run_golden(depts.SKKU_STD_DEPT, router)
    run.snapshot_all("std_pinned_only_page1")


async def test_std_page0_connect_error_marks_source_down():
    router = FixtureRouter().fail(
        depts.std_list_url(0), httpx.ConnectError("connection refused")
    )
    run = await run_golden(depts.SKKU_STD_DEPT, router)
    run.snapshot_all("std_source_down")
    assert run.results[0].source_down is True


async def test_gnuboard_cold_two_pages():
    router = (
        FixtureRouter()
        .serve(depts.gnb_list_url(0), "gnuboard/list_p0.html")
        .serve(depts.gnb_list_url(1), "gnuboard/list_p1.html")
        .serve(depts.gnb_list_url(2), "gnuboard/empty.html")
    )
    for article_no in (501, 502, 503, 504, 505):
        router.serve(depts.gnb_detail_url(article_no), f"gnuboard/detail_{article_no}.html")
    run = await run_golden(depts.GNUBOARD_DEPT, router)
    run.snapshot_all("gnb_cold")


async def test_std_full_sweep_no_store_consult():
    """incremental=False: the 'core requires nothing' acceptance case in its
    current-API form (재조준: PR 6 swaps this to FullSweep()+NullSink and the
    same golden must pass). No find_existing_meta, no bulk_touch — every item
    upserted, stop on empty page."""
    run = await run_golden(depts.SKKU_STD_DEPT, _std_cold_router(), incremental=False)
    run.snapshot_all("std_full_sweep")
    op_names = [op[0] for op in run.ops_delta()]
    assert "bulk_write" not in op_names


async def test_std_null_content_backfill():
    """Pre-seeded content:null doc is re-fetched BEFORE the page loop via the
    intentionally divergent backfill path: exact 7-field $set, no
    build_notice, no editHistory (위험 ④ — do not 'unify' this)."""
    collection = FakeCollection()
    seed(
        collection,
        [
            {
                "articleNo": 106,
                "sourceId": "golden-std",
                "title": "휴학·복학 신청 절차",
                "date": "2026-03-14",
                "content": None,
                "contentText": None,
                "detailPath": "?mode=view&articleNo=106&article.offset=0&articleLimit=10",
                "views": 5,
            }
        ],
    )
    router = (
        FixtureRouter()
        .serve(depts.std_list_url(0), "skku_standard/empty.html")
        .serve(depts.std_detail_url(106), "skku_standard/detail_106.html")
    )
    run = await run_golden(depts.SKKU_STD_DEPT, router, collection=collection)
    run.snapshot_all("std_null_backfill")

    backfill_updates = [op for op in run.ops_delta() if op[0] == "update_one"]
    assert len(backfill_updates) == 1
    set_fields = sorted(backfill_updates[0][1]["update"]["$set"])
    assert set_fields == [
        "attachments",
        "cleanHtml",
        "cleanMarkdown",
        "content",
        "contentHash",
        "contentText",
        "crawledAt",
    ]
