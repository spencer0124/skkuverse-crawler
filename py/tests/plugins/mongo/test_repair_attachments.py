"""Draining the two populations of broken attachment links.

cal's links were never wrong, only unusable: NFUpload wants a Referer and
the strategy stored none, so the fix is a field the document already
implies. dorm's links went wrong after the fact — the board reissues
``attach_no`` on edit, so a stored id can come to name a different file
entirely, and only the live page knows the current one.

These pin that each population gets the repair it needs, that a second run
is a no-op, and that a failed refetch never destroys what is stored.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from skkuverse_crawler.modules.notices.models import NoticeDetail
from skkuverse_crawler.plugins.mongo.repair_attachments import (
    backfill_referer,
    repair_attachments,
)
from tests.support.fake_mongo import FakeCollection

CAL_DEPT = {
    "id": "cal-undergrad",
    "strategy": "custom-php",
    "baseUrl": "https://cal.skku.edu/index.php",
    "boardParams": {"hCode": "BOARD", "bo_idx": "17"},
    "selectors": {"detailContent": "div.board_content"},
}
DORM_DEPT = {
    "id": "dorm-nsc",
    "strategy": "jsp-dorm",
    "baseUrl": "https://dorm.skku.edu/dorm_suwon/notice/notice_all.jsp",
    "selectors": {"detailContent": "div", "attachmentLink": "a"},
}
# skku-standard has no repair mode: its links are fine and refetching 6,000
# notices to prove it would be the opposite of a targeted drain.
MAIN_DEPT = {"id": "skku-main", "strategy": "skku-standard", "baseUrl": "https://www.skku.edu/x.do"}

CAL_URL = "https://cal.skku.edu/NFUpload/nfupload_down.php?tmp_name=a.pdf&name=poster.pdf"
CAL_SOURCE_URL = "https://cal.skku.edu/index.php?page=view&idx=1309"
DORM_OLD = "https://dorm.skku.edu/_custom/skku/_common/board/download.jsp?attach_no=7470"
DORM_NEW = "https://dorm.skku.edu/_custom/skku/_common/board/download.jsp?attach_no=7473"


def _doc(source_id: str, attachments: list[dict], **overrides) -> dict:
    doc = {
        "articleNo": 1,
        "sourceId": source_id,
        "sourceUrl": CAL_SOURCE_URL,
        "detailPath": "?mode=view&articleNo=1",
        "attachments": attachments,
    }
    doc.update(overrides)
    return doc


async def _store(*docs) -> FakeCollection:
    collection = FakeCollection()
    for doc in docs:
        await collection.update_one(
            {"articleNo": doc["articleNo"], "sourceId": doc["sourceId"]},
            {"$set": doc},
            upsert=True,
        )
    return collection


async def _run(collection, departments, detail=None, **kwargs):
    """Drive the repair against a fake DB, config and network."""
    strategy = AsyncMock()
    strategy.crawl_detail.return_value = detail

    with patch(
        "skkuverse_crawler.shared.db.get_db", return_value={"notices": collection},
    ), patch(
        "skkuverse_crawler.modules.notices.config.loader.load_and_validate",
        return_value=departments,
    ), patch(
        "skkuverse_crawler.plugins.mongo.repair_attachments.STRATEGY_MAP",
        {"jsp-dorm": lambda _fetcher: strategy, "custom-php": lambda _fetcher: strategy},
    ), patch("skkuverse_crawler.shared.fetcher.Fetcher", AsyncMock):
        return await repair_attachments(**kwargs)


# ── backfill_referer, on its own ──────────────────────────────────────────


class TestBackfillReferer:
    def test_adds_the_detail_url(self):
        result = backfill_referer([{"name": "a.pdf", "url": CAL_URL}], CAL_SOURCE_URL)
        assert result == [{"name": "a.pdf", "url": CAL_URL, "referer": CAL_SOURCE_URL}]

    def test_leaves_an_existing_referer_alone(self):
        """Idempotence lives here: a second run must find nothing to do."""
        already = [{"name": "a.pdf", "url": CAL_URL, "referer": "https://cal.skku.edu/other"}]
        assert backfill_referer(already, CAL_SOURCE_URL) is None

    def test_no_source_url_is_no_change(self):
        """An empty referer would satisfy the validator and fix nothing —
        worse than leaving the gap visible."""
        assert backfill_referer([{"name": "a.pdf", "url": CAL_URL}], "") is None

    def test_repairs_only_the_attachments_that_need_it(self):
        mixed = [
            {"name": "has.pdf", "url": CAL_URL, "referer": "https://cal.skku.edu/keep"},
            {"name": "lacks.pdf", "url": CAL_URL},
        ]
        result = backfill_referer(mixed, CAL_SOURCE_URL)
        assert result is not None
        assert result[0]["referer"] == "https://cal.skku.edu/keep"
        assert result[1]["referer"] == CAL_SOURCE_URL


# ── custom-php: offline referer backfill ──────────────────────────────────


class TestCustomPhpRepair:
    async def test_dry_run_reports_without_writing(self):
        collection = await _store(_doc("cal-undergrad", [{"name": "a.pdf", "url": CAL_URL}]))
        report = await _run(collection, [CAL_DEPT])

        assert report.repaired == 1
        assert "referer" not in collection.docs[0]["attachments"][0]

    async def test_apply_writes_the_referer(self):
        collection = await _store(_doc("cal-undergrad", [{"name": "a.pdf", "url": CAL_URL}]))
        report = await _run(collection, [CAL_DEPT], apply=True)

        assert report.repaired == 1
        assert collection.docs[0]["attachments"][0]["referer"] == CAL_SOURCE_URL

    async def test_second_run_is_a_no_op(self):
        collection = await _store(_doc("cal-undergrad", [{"name": "a.pdf", "url": CAL_URL}]))
        await _run(collection, [CAL_DEPT], apply=True)
        again = await _run(collection, [CAL_DEPT], apply=True)

        assert again.repaired == 0
        assert again.already_consistent == 1

    async def test_it_does_not_fetch(self):
        """The detail URL is already stored, so a network call here would be
        thousands of needless requests against a site that rate-limits."""
        collection = await _store(_doc("cal-undergrad", [{"name": "a.pdf", "url": CAL_URL}]))
        strategy = AsyncMock()

        with patch(
            "skkuverse_crawler.shared.db.get_db", return_value={"notices": collection},
        ), patch(
            "skkuverse_crawler.modules.notices.config.loader.load_and_validate",
            return_value=[CAL_DEPT],
        ), patch(
            "skkuverse_crawler.plugins.mongo.repair_attachments.STRATEGY_MAP",
            {"custom-php": lambda _f: strategy},
        ):
            await repair_attachments(apply=True)

        strategy.crawl_detail.assert_not_called()


# ── jsp-dorm: refetch the rotated id ──────────────────────────────────────


class TestDormRepair:
    async def test_replaces_a_rotated_attach_no(self):
        collection = await _store(_doc("dorm-nsc", [{"name": "guide.pdf", "url": DORM_OLD}]))
        detail = NoticeDetail(
            content="<p>본문</p>", contentText="본문",
            attachments=[{"name": "guide.pdf", "url": DORM_NEW}],
        )
        report = await _run(collection, [DORM_DEPT], detail=detail, apply=True)

        assert report.repaired == 1
        assert collection.docs[0]["attachments"] == [{"name": "guide.pdf", "url": DORM_NEW}]

    async def test_unchanged_attachments_are_not_rewritten(self):
        collection = await _store(_doc("dorm-nsc", [{"name": "guide.pdf", "url": DORM_OLD}]))
        detail = NoticeDetail(
            content="<p>본문</p>", contentText="본문",
            attachments=[{"name": "guide.pdf", "url": DORM_OLD}],
        )
        report = await _run(collection, [DORM_DEPT], detail=detail, apply=True)

        assert report.repaired == 0
        assert report.already_consistent == 1

    async def test_a_failed_refetch_never_blanks_what_is_stored(self):
        """The destructive failure mode this guards against: a notice that
        404s during the pass would otherwise have its real attachment list
        replaced with the empty one a failed fetch returns."""
        stored = [{"name": "guide.pdf", "url": DORM_OLD}]
        collection = await _store(_doc("dorm-nsc", stored))
        report = await _run(collection, [DORM_DEPT], detail=None, apply=True)

        assert report.unfetchable == 1
        assert report.repaired == 0
        assert collection.docs[0]["attachments"] == stored


# ── scope ─────────────────────────────────────────────────────────────────


class TestScope:
    async def test_strategies_with_no_repair_mode_are_left_alone(self):
        """A targeted drain, not a corpus-wide refetch."""
        collection = await _store(
            _doc("skku-main", [{"name": "a.pdf", "url": "https://www.skku.edu/f"}]),
        )
        report = await _run(collection, [MAIN_DEPT])

        assert report.scanned == 0
        assert report.repaired == 0

    async def test_source_filter_narrows_within_the_repairable_set(self):
        collection = await _store(
            _doc("cal-undergrad", [{"name": "a.pdf", "url": CAL_URL}]),
            _doc("dorm-nsc", [{"name": "b.pdf", "url": DORM_OLD}]),
        )
        report = await _run(
            collection, [CAL_DEPT, DORM_DEPT], dept_filter=("cal-undergrad",),
        )

        assert report.scanned == 1
        assert report.by_source == {"cal-undergrad": 1}

    async def test_notices_without_attachments_are_never_scanned(self):
        collection = await _store(_doc("cal-undergrad", []))
        report = await _run(collection, [CAL_DEPT])

        assert report.scanned == 0


# ── force_refetch: the files the source deleted ───────────────────────────


class TestForceRefetch:
    async def test_it_drops_attachments_the_source_removed(self):
        """The third failure, which neither offline repair can see.

        cal-grad 1353's detail page carries no attachment links any more,
        so its stored URLs are well-formed links to nothing. Tier-2 will
        not catch it either: removing a file does not move the content
        hash.
        """
        collection = await _store(_doc("cal-undergrad", [{"name": "gone.pdf", "url": CAL_URL}]))
        detail = NoticeDetail(content="<p>본문</p>", contentText="본문", attachments=[])
        report = await _run(
            collection, [CAL_DEPT], detail=detail, apply=True, force_refetch=True,
        )

        assert report.repaired == 1
        assert collection.docs[0]["attachments"] == []

    async def test_without_the_flag_the_same_notice_is_repaired_offline(self):
        """The control: the flag is what changes the behaviour, not the doc.

        Default stays offline so the common case costs no requests.
        """
        collection = await _store(_doc("cal-undergrad", [{"name": "gone.pdf", "url": CAL_URL}]))
        detail = NoticeDetail(content="<p>본문</p>", contentText="본문", attachments=[])
        await _run(collection, [CAL_DEPT], detail=detail, apply=True)

        assert collection.docs[0]["attachments"][0]["referer"] == CAL_SOURCE_URL

    async def test_a_failed_refetch_still_never_blanks(self):
        stored = [{"name": "keep.pdf", "url": CAL_URL}]
        collection = await _store(_doc("cal-undergrad", stored))
        report = await _run(
            collection, [CAL_DEPT], detail=None, apply=True, force_refetch=True,
        )

        assert report.unfetchable == 1
        assert collection.docs[0]["attachments"] == stored
