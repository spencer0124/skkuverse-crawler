"""Level-2 conformance: the flagship golden replayed on a real MongoDB.

Runs golden case 1 (skku-standard, all three rounds) through the same
harness but against a real Motor collection, then requires the final
collection state to equal the COMMITTED round-3 state snapshot. This welds
the two trust links into one assertion: if the fake lied anywhere in the
crawl's op stream, the real backend's final state diverges from the golden.

(`.ops` round-trip counting stays fake-only — real Mongo cannot expose it.)
"""
from __future__ import annotations

import json

import pytest

from tests.characterization import depts
from tests.characterization.harness import SNAPSHOTS_DIR, FixtureRouter, run_golden
from tests.characterization.test_crawl_golden import _std_cold_router
from tests.support.normalize import normalize_bson, sort_docs

pytestmark = pytest.mark.mongo


async def test_three_rounds_on_real_mongo_match_committed_golden(real_collection):
    await run_golden(depts.SKKU_STD_DEPT, _std_cold_router(), collection=real_collection)

    warm_router = FixtureRouter().serve(depts.std_list_url(0), "skku_standard/list_p0.html")
    await run_golden(depts.SKKU_STD_DEPT, warm_router, collection=real_collection)

    tampered_router = (
        FixtureRouter()
        .serve(depts.std_list_url(0), "skku_standard/list_p0_tampered.html")
        .serve(depts.std_detail_url(101), "skku_standard/detail_101.html")
    )
    await run_golden(depts.SKKU_STD_DEPT, tampered_router, collection=real_collection)

    real_state = sort_docs(
        normalize_bson(
            [doc async for doc in real_collection.find({})], datetime_to="placeholder"
        )
    )
    golden_path = SNAPSHOTS_DIR / "std_three_rounds" / "round3_tampered_state.json"
    committed_golden = json.loads(golden_path.read_text())
    assert real_state == committed_golden
