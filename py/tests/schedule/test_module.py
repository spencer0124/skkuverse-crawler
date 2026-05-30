from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
from httpx import Response

from skkuverse_crawler.schedule import fetcher_parser as fp
from skkuverse_crawler.schedule.module import crawl_schedule

from .test_parser import AUG, build_page


@pytest.fixture()
def db_collection():
    """Patch the schedule module's get_db so crawl_schedule uses a mock.

    Mirrors how notices_summary tests patch get_db in the consuming module's
    namespace (a `from ..shared.db import get_db` binding is not reached by
    conftest's patch on shared.db.get_db).
    """
    coll = AsyncMock()
    coll.find_one = AsyncMock(return_value=None)
    coll.update_one = AsyncMock(return_value=SimpleNamespace(upserted_id="x"))
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=coll)

    async def fake_get_db():
        return mock_db

    with patch("skkuverse_crawler.schedule.module.get_db", side_effect=fake_get_db):
        yield coll


@respx.mock
async def test_crawl_current_and_future_only(db_collection):
    base = build_page(served_year=2026, dropdown_years=(2024, 2025, 2026))
    respx.get(fp.year_url(2026)).mock(
        return_value=Response(200, text=build_page(served_year=2026, schedule_obj=AUG))
    )
    respx.get(fp.BASE_URL).mock(return_value=Response(200, text=base))

    counts = await crawl_schedule()

    # Past years (2024, 2025) are below current -> never fetched/stored.
    assert counts["years_checked"] == 1
    assert counts["inserted"] == 1
    filters = [c.args[0] for c in db_collection.update_one.call_args_list]
    assert filters == [{"_id": 2026}]


@respx.mock
async def test_silent_fallback_year_not_stored(db_collection):
    """Headline guard: an unpublished future year serves current data; we must
    NOT store current-year data under the future year's _id."""
    # Base advertises a future year 2027, current served year is 2026.
    base = build_page(served_year=2026, dropdown_years=(2025, 2026, 2027))
    respx.get(fp.year_url(2026)).mock(
        return_value=Response(200, text=build_page(served_year=2026, schedule_obj=AUG))
    )
    # 2027 page silently falls back to 2026 (served_year == 2026, not 2027).
    respx.get(fp.year_url(2027)).mock(
        return_value=Response(200, text=build_page(served_year=2026, schedule_obj=AUG))
    )
    respx.get(fp.BASE_URL).mock(return_value=Response(200, text=base))

    counts = await crawl_schedule()

    assert counts["years_checked"] == 2
    assert counts["inserted"] == 1
    assert counts["skipped"] == 1
    assert counts["errors"] == 0

    filters = [c.args[0] for c in db_collection.update_one.call_args_list]
    assert {"_id": 2026} in filters
    assert {"_id": 2027} not in filters


@respx.mock
async def test_unchanged_year_is_skipped(db_collection):
    """Second crawl with identical content must not write (yearHash gate)."""
    page = build_page(served_year=2026, schedule_obj=AUG)
    events = fp.parse_events(page)
    db_collection.find_one = AsyncMock(
        return_value={"yearHash": fp.compute_year_hash(events)}
    )

    base = build_page(served_year=2026, dropdown_years=(2024, 2025, 2026))
    respx.get(fp.year_url(2026)).mock(return_value=Response(200, text=page))
    respx.get(fp.BASE_URL).mock(return_value=Response(200, text=base))

    counts = await crawl_schedule()

    assert counts["skipped"] == 1
    assert counts["inserted"] == 0
    db_collection.update_one.assert_not_awaited()


@respx.mock
async def test_no_years_discovered_returns_early(db_collection):
    respx.get(fp.BASE_URL).mock(
        return_value=Response(200, text="<html><body>no select</body></html>")
    )

    counts = await crawl_schedule()

    assert counts == {
        "years_checked": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    }
    db_collection.update_one.assert_not_awaited()


@respx.mock
async def test_requested_year_not_published_is_skipped(db_collection):
    base = build_page(served_year=2026, dropdown_years=(2024, 2025, 2026))
    respx.get(fp.BASE_URL).mock(return_value=Response(200, text=base))

    counts = await crawl_schedule(year=2030)

    assert counts["years_checked"] == 0
    db_collection.update_one.assert_not_awaited()
