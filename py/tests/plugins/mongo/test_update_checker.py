from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx

import pytest

from skkuverse_crawler.modules.notices.image_verifier import ImageCheckResult
from skkuverse_crawler.core.pipeline import ContentDoc, StageContext
from skkuverse_crawler.modules.notices.models import NoticeDetail, NoticeListItem
from skkuverse_crawler.modules.notices.normalizer import build_notice
from skkuverse_crawler.modules.notices.stages import (
    DEFAULT_PIPELINE,
    ContentFields,
    derive_content_fields,
)
from tests.support.fake_mongo import FakeCollection
from skkuverse_crawler.plugins.mongo.update_checker import _check_department


MOCK_DEPT = {
    "id": "test-dept",
    "name": "테스트학과",
    "baseUrl": "https://example.com",
    "strategy": "skku-standard",
}


# Tests below fall into two groups, and the split is deliberate.
#
# Tests about *control flow* — change rate, 404 counters, whether an update
# fires at all — only need to steer hash equality, so they stub the
# derivation with these helpers. Tests about *what gets stored* run the real
# derive_content_fields, because stubbing it would mock away the thing they
# exist to prove.


def _fields_with_hash(hash_value: str, html: str):
    """Stub derivation with a fixed hash, for tests that only need equality."""

    async def _derive(*args, **kwargs) -> ContentFields:
        return ContentFields(
            content=html,
            contentText="본문",
            cleanHtml=html,
            cleanMarkdown="본문",
            contentHash=hash_value,
        )

    return _derive


def _fields_from(hash_fn, html: str):
    """Same, for tests that vary the hash per call (rate anomalies)."""

    async def _derive(*args, **kwargs) -> ContentFields:
        return ContentFields(
            content=html,
            contentText="본문",
            cleanHtml=html,
            cleanMarkdown="본문",
            contentHash=hash_fn(html),
        )

    return _derive


class TestCheckDepartmentHashComparison:
    """_check_department의 hash 비교 로직."""

    async def test_same_hash_no_update(self, mock_collection):
        """hash 동일 → 업데이트 안 함."""
        notices = [{
            "articleNo": 1, "sourceId": "test-dept",
            "detailPath": "?articleNo=1", "contentHash": "existing_hash", "title": "제목",
        }]
        strategy = AsyncMock()
        strategy.crawl_detail.return_value = NoticeDetail(
            content="<p>본문</p>", contentText="본문", attachments=[],
        )
        logger = MagicMock()

        with patch(
            "skkuverse_crawler.plugins.mongo.update_checker.derive_content_fields",
            _fields_with_hash("existing_hash", "<p>본문</p>"),
        ), patch(
            "skkuverse_crawler.plugins.mongo.update_checker.STRATEGY_MAP",
            {"skku-standard": MagicMock(return_value=strategy)},
        ):
            result = await _check_department(MOCK_DEPT, notices, mock_collection, AsyncMock(), logger)

        assert result.content_changed == 0
        mock_collection.update_one.assert_not_awaited()

    async def test_different_hash_updates_with_tier2_source(self, mock_collection):
        """hash 다름 → $set + $push + $inc, source=tier2."""
        notices = [{
            "articleNo": 1, "sourceId": "test-dept",
            "detailPath": "?articleNo=1", "contentHash": "old_hash", "title": "제목",
        }]
        strategy = AsyncMock()
        strategy.crawl_detail.return_value = NoticeDetail(
            content="<p>새 본문</p>", contentText="새 본문", attachments=[],
        )
        logger = MagicMock()

        with patch(
            "skkuverse_crawler.plugins.mongo.update_checker.derive_content_fields",
            _fields_with_hash("new_hash", "<p>새 본문</p>"),
        ), patch(
            "skkuverse_crawler.plugins.mongo.update_checker.STRATEGY_MAP",
            {"skku-standard": MagicMock(return_value=strategy)},
        ):
            result = await _check_department(MOCK_DEPT, notices, mock_collection, AsyncMock(), logger)

        assert result.content_changed == 1
        mock_collection.update_one.assert_awaited_once()

        update_doc = mock_collection.update_one.call_args[0][1]
        assert update_doc["$set"]["contentHash"] == "new_hash"
        assert update_doc["$inc"]["editCount"] == 1

        edit_entry = update_doc["$push"]["editHistory"]["$each"][0]
        assert edit_entry["source"] == "tier2"
        assert edit_entry["oldHash"] == "old_hash"
        assert edit_entry["newHash"] == "new_hash"

    async def test_null_hash_backfill(self, mock_collection):
        """old hash None (backfill) → contentHash만 세팅, editHistory push 안 함."""
        notices = [{
            "articleNo": 1, "sourceId": "test-dept",
            "detailPath": "?articleNo=1", "contentHash": None, "title": "제목",
        }]
        strategy = AsyncMock()
        strategy.crawl_detail.return_value = NoticeDetail(
            content="<p>본문</p>", contentText="본문", attachments=[],
        )
        logger = MagicMock()

        with patch(
            "skkuverse_crawler.plugins.mongo.update_checker.derive_content_fields",
            _fields_with_hash("new_hash", "<p>본문</p>"),
        ), patch(
            "skkuverse_crawler.plugins.mongo.update_checker.STRATEGY_MAP",
            {"skku-standard": MagicMock(return_value=strategy)},
        ):
            result = await _check_department(MOCK_DEPT, notices, mock_collection, AsyncMock(), logger)

        assert result.hash_backfilled == 1
        assert result.content_changed == 0

        update_doc = mock_collection.update_one.call_args[0][1]
        assert update_doc["$set"]["contentHash"] == "new_hash"
        assert "$push" not in update_doc
        assert "$inc" not in update_doc


class TestCheckDepartmentEdgeCases:

    async def test_no_detail_path_skipped(self, mock_collection):
        """detailPath 없음 → skipped_no_detail 증가."""
        notices = [{
            "articleNo": 1, "sourceId": "test-dept",
            "detailPath": "", "contentHash": "hash", "title": "제목",
        }]
        logger = MagicMock()

        with patch(
            "skkuverse_crawler.plugins.mongo.update_checker.STRATEGY_MAP",
            {"skku-standard": MagicMock()},
        ):
            result = await _check_department(MOCK_DEPT, notices, mock_collection, AsyncMock(), logger)

        assert result.skipped_no_detail == 1
        assert result.total_checked == 0

    async def test_fetch_error_continues(self, mock_collection):
        """crawl_detail 예외 → fetch_errors 증가, 다음 notice 계속 처리."""
        notices = [
            {"articleNo": 1, "sourceId": "test-dept",
             "detailPath": "?a=1", "contentHash": "h1", "title": "제목1"},
            {"articleNo": 2, "sourceId": "test-dept",
             "detailPath": "?a=2", "contentHash": "h2", "title": "제목2"},
        ]
        strategy = AsyncMock()
        strategy.crawl_detail.side_effect = [
            Exception("timeout"),  # 첫 번째 실패
            NoticeDetail(content="<p>ok</p>", contentText="ok", attachments=[]),  # 두 번째 성공
        ]
        logger = MagicMock()

        with patch(
            "skkuverse_crawler.plugins.mongo.update_checker.derive_content_fields",
            _fields_with_hash("h2", "<p>ok</p>"),
        ), patch(
            "skkuverse_crawler.plugins.mongo.update_checker.STRATEGY_MAP",
            {"skku-standard": MagicMock(return_value=strategy)},
        ):
            result = await _check_department(MOCK_DEPT, notices, mock_collection, AsyncMock(), logger)

        assert result.fetch_errors == 1
        assert result.total_checked == 1  # 두 번째만 checked


class TestChangeRateAnomaly:
    """content_changed 비율 이상 감지."""

    async def test_error_on_very_high_rate(self, mock_collection):
        """>80% → logger.error (likely determinism bug)."""
        # 10건 체크, 9건 변경 = 90%
        notices = [
            {"articleNo": i, "sourceId": "test-dept",
             "detailPath": f"?a={i}", "contentHash": f"old_{i}", "title": f"제목{i}"}
            for i in range(10)
        ]
        strategy = AsyncMock()
        strategy.crawl_detail.return_value = NoticeDetail(
            content="<p>새 본문</p>", contentText="새 본문", attachments=[],
        )
        logger = MagicMock()

        call_count = 0
        def varying_hash(html):
            nonlocal call_count
            call_count += 1
            # 9/10 다른 hash, 1개는 동일
            if call_count == 5:
                return "old_4"
            return f"new_{call_count}"

        with patch(
            "skkuverse_crawler.plugins.mongo.update_checker.derive_content_fields",
            _fields_from(varying_hash, "<p>새 본문</p>"),
        ), patch(
            "skkuverse_crawler.plugins.mongo.update_checker.STRATEGY_MAP",
            {"skku-standard": MagicMock(return_value=strategy)},
        ):
            result = await _check_department(MOCK_DEPT, notices, mock_collection, AsyncMock(), logger)

        assert result.content_changed == 9
        logger.error.assert_any_call(
            "likely_determinism_bug",
            source_id="test-dept",
            rate=0.9,
            content_changed=9,
            checked=10,
        )

    async def test_warning_on_moderate_rate(self, mock_collection):
        """>30% but <=80% → logger.warning."""
        # 10건 체크, 5건 변경 = 50%
        notices = [
            {"articleNo": i, "sourceId": "test-dept",
             "detailPath": f"?a={i}", "contentHash": f"old_{i}", "title": f"제목{i}"}
            for i in range(10)
        ]
        strategy = AsyncMock()
        strategy.crawl_detail.return_value = NoticeDetail(
            content="<p>본문</p>", contentText="본문", attachments=[],
        )
        logger = MagicMock()

        call_count = 0
        def half_changed_hash(html):
            nonlocal call_count
            call_count += 1
            if call_count <= 5:
                return f"new_{call_count}"  # 다름
            return f"old_{call_count - 1}"  # 동일

        with patch(
            "skkuverse_crawler.plugins.mongo.update_checker.derive_content_fields",
            _fields_from(half_changed_hash, "<p>본문</p>"),
        ), patch(
            "skkuverse_crawler.plugins.mongo.update_checker.STRATEGY_MAP",
            {"skku-standard": MagicMock(return_value=strategy)},
        ):
            result = await _check_department(MOCK_DEPT, notices, mock_collection, AsyncMock(), logger)

        assert result.content_changed == 5
        logger.warning.assert_any_call(
            "high_change_rate",
            source_id="test-dept",
            rate=0.5,
            content_changed=5,
            checked=10,
        )
        logger.error.assert_not_called()

    async def test_no_warning_on_low_rate(self, mock_collection):
        """<=30% → 알람 없음."""
        notices = [{
            "articleNo": 1, "sourceId": "test-dept",
            "detailPath": "?a=1", "contentHash": "same", "title": "제목",
        }]
        strategy = AsyncMock()
        strategy.crawl_detail.return_value = NoticeDetail(
            content="<p>본문</p>", contentText="본문", attachments=[],
        )
        logger = MagicMock()

        with patch(
            "skkuverse_crawler.plugins.mongo.update_checker.derive_content_fields",
            _fields_with_hash("same", "<p>본문</p>"),
        ), patch(
            "skkuverse_crawler.plugins.mongo.update_checker.STRATEGY_MAP",
            {"skku-standard": MagicMock(return_value=strategy)},
        ):
            result = await _check_department(MOCK_DEPT, notices, mock_collection, AsyncMock(), logger)

        assert result.content_changed == 0
        logger.warning.assert_not_called()
        logger.error.assert_not_called()


def _make_404_error():
    """Create a mock httpx 404 response error."""
    request = httpx.Request("GET", "https://example.com/404")
    response = httpx.Response(404, request=request)
    return httpx.HTTPStatusError("Not Found", request=request, response=response)


class TestSoftDelete:
    """404 → consecutiveFailures 증가 → 3회 시 soft delete."""

    async def test_single_404_increments_counter(self, mock_collection):
        notices = [{
            "articleNo": 1, "sourceId": "test-dept",
            "detailPath": "?a=1", "contentHash": "h", "title": "제목",
            "consecutiveFailures": 0,
        }]
        strategy = AsyncMock()
        strategy.crawl_detail.side_effect = _make_404_error()
        logger = MagicMock()

        # find_one_and_update returns the updated doc (failures=1, not deleted)
        mock_collection.find_one_and_update.return_value = {
            "articleNo": 1, "sourceId": "test-dept",
            "consecutiveFailures": 1, "isDeleted": False,
        }

        with patch(
            "skkuverse_crawler.plugins.mongo.update_checker.STRATEGY_MAP",
            {"skku-standard": MagicMock(return_value=strategy)},
        ):
            result = await _check_department(MOCK_DEPT, notices, mock_collection, AsyncMock(), logger)

        assert result.not_found == 1
        assert result.soft_deleted == 0
        mock_collection.find_one_and_update.assert_called_once()

    async def test_third_404_triggers_soft_delete(self, mock_collection):
        notices = [{
            "articleNo": 1, "sourceId": "test-dept",
            "detailPath": "?a=1", "contentHash": "h", "title": "제목",
            "consecutiveFailures": 2,  # 이미 2회, 이번이 3번째
        }]
        strategy = AsyncMock()
        strategy.crawl_detail.side_effect = _make_404_error()
        logger = MagicMock()

        # find_one_and_update returns the updated doc (failures=3, deleted)
        mock_collection.find_one_and_update.return_value = {
            "articleNo": 1, "sourceId": "test-dept",
            "consecutiveFailures": 3, "isDeleted": True,
        }

        with patch(
            "skkuverse_crawler.plugins.mongo.update_checker.STRATEGY_MAP",
            {"skku-standard": MagicMock(return_value=strategy)},
        ):
            result = await _check_department(MOCK_DEPT, notices, mock_collection, AsyncMock(), logger)

        assert result.soft_deleted == 1
        mock_collection.find_one_and_update.assert_called_once()

    async def test_successful_fetch_resets_counter(self, mock_collection):
        """정상 fetch → consecutiveFailures 리셋."""
        notices = [{
            "articleNo": 1, "sourceId": "test-dept",
            "detailPath": "?a=1", "contentHash": "same", "title": "제목",
            "consecutiveFailures": 2,
        }]
        strategy = AsyncMock()
        strategy.crawl_detail.return_value = NoticeDetail(
            content="<p>본문</p>", contentText="본문", attachments=[],
        )
        logger = MagicMock()

        with patch(
            "skkuverse_crawler.plugins.mongo.update_checker.derive_content_fields",
            _fields_with_hash("same", "<p>본문</p>"),
        ), patch(
            "skkuverse_crawler.plugins.mongo.update_checker.STRATEGY_MAP",
            {"skku-standard": MagicMock(return_value=strategy)},
        ):
            await _check_department(MOCK_DEPT, notices, mock_collection, AsyncMock(), logger)

        # consecutiveFailures > 0이었으므로 리셋 쿼리 발생
        mock_collection.update_one.assert_awaited_once()
        update_doc = mock_collection.update_one.call_args[0][1]
        assert update_doc["$set"]["consecutiveFailures"] == 0

    async def test_mass_404_skips_counter_increment(self, mock_collection):
        """학과 전체 >50% 404 (5건+) → 서버 문제로 판단, 카운터 증가 skip."""
        # 6건 중 4건 404 (66%) → mass 404 (>= 5건 threshold)
        notices = [
            {"articleNo": i, "sourceId": "test-dept",
             "detailPath": f"?a={i}", "contentHash": f"h{i}", "title": f"제목{i}",
             "consecutiveFailures": 0}
            for i in range(6)
        ]
        strategy = AsyncMock()
        strategy.crawl_detail.side_effect = [
            _make_404_error(),
            _make_404_error(),
            _make_404_error(),
            _make_404_error(),
            NoticeDetail(content="<p>ok</p>", contentText="ok", attachments=[]),
            NoticeDetail(content="<p>ok2</p>", contentText="ok2", attachments=[]),
        ]
        logger = MagicMock()

        call_count = 0
        def match_hash(html):
            nonlocal call_count
            call_count += 1
            return f"h{call_count + 3}"  # h4, h5 → match

        with patch(
            "skkuverse_crawler.plugins.mongo.update_checker.derive_content_fields",
            _fields_from(match_hash, "<p>ok</p>"),
        ), patch(
            "skkuverse_crawler.plugins.mongo.update_checker.STRATEGY_MAP",
            {"skku-standard": MagicMock(return_value=strategy)},
        ):
            result = await _check_department(MOCK_DEPT, notices, mock_collection, AsyncMock(), logger)

        assert result.not_found == 4
        assert result.soft_deleted == 0  # 카운터 증가 안 함
        logger.error.assert_any_call(
            "mass_404_detected",
            source_id="test-dept",
            not_found=4,
            total_attempted=6,
        )


class TestCutoffFloorDate:
    """SERVICE_START_DATE와 window_days의 max 처리."""

    def test_floor_date_wins_when_window_is_wider(self):
        from skkuverse_crawler.modules.notices.constants import SERVICE_START_DATE
        # window cutoff가 floor date보다 이전 → floor date 사용
        assert max(SERVICE_START_DATE, "2026-03-01") == SERVICE_START_DATE

    def test_window_wins_when_narrower(self):
        from skkuverse_crawler.modules.notices.constants import SERVICE_START_DATE
        # window cutoff가 floor date보다 이후 → window cutoff 사용
        assert max(SERVICE_START_DATE, "2026-05-01") == "2026-05-01"


class TestSoftDeleteAgainstTheFakeStore:
    """The 404 counter as a state transition, not a stipulated response.

    The mock-based tests above hand find_one_and_update its return value,
    so they pin how the checker REACTS to a store answer. These run the
    aggregation pipeline against FakeCollection — whose fidelity level-1
    conformance pins against real Mongo — so they check that the pipeline
    actually produces that answer.
    """

    @staticmethod
    async def _run_404(collection, seed: dict) -> tuple:
        await collection.update_one(
            {"articleNo": 1, "sourceId": "test-dept"},
            {"$set": {"detailPath": "?a=1", "title": "제목", **seed}},
            upsert=True,
        )
        strategy = AsyncMock()
        strategy.crawl_detail.side_effect = _make_404_error()
        notices = [{"articleNo": 1, "sourceId": "test-dept", "detailPath": "?a=1", **seed}]

        with patch(
            "skkuverse_crawler.plugins.mongo.update_checker.STRATEGY_MAP",
            {"skku-standard": MagicMock(return_value=strategy)},
        ):
            result = await _check_department(
                MOCK_DEPT, notices, collection, AsyncMock(), MagicMock()
            )
        # find(), not find_one() — the fake implements only what src calls.
        cursor = collection.find({"articleNo": 1, "sourceId": "test-dept"})
        stored = [doc async for doc in cursor][0]
        return result, stored

    async def test_first_404_increments_without_deleting(self):
        collection = FakeCollection()
        result, stored = await self._run_404(collection, {"consecutiveFailures": 0})
        assert stored["consecutiveFailures"] == 1
        assert stored["isDeleted"] is False
        assert result.soft_deleted == 0

    async def test_third_404_flips_the_delete_flag(self):
        collection = FakeCollection()
        result, stored = await self._run_404(collection, {"consecutiveFailures": 2})
        assert stored["consecutiveFailures"] == 3
        assert stored["isDeleted"] is True
        assert result.soft_deleted == 1

    async def test_already_deleted_is_not_counted_twice(self):
        """soft_deleted counts transitions, not states — a doc that was
        already flagged must not inflate the number again."""
        collection = FakeCollection()
        result, stored = await self._run_404(
            collection, {"consecutiveFailures": 5, "isDeleted": True}
        )
        assert stored["consecutiveFailures"] == 6
        assert result.soft_deleted == 0

    async def test_missing_counter_field_starts_at_one(self):
        collection = FakeCollection()
        _, stored = await self._run_404(collection, {})
        assert stored["consecutiveFailures"] == 1
        assert stored["isDeleted"] is False




class TestTier2StoresTheSameFieldsAsACrawl:
    """The real pipeline, not a stub — these exist to catch Tier-2 drifting
    from the crawl path again.

    It had drifted four ways, all silent, and the fourth is why the other
    three kept coming back: Tier-2 did not measure images. The crawl injects
    width/height on every <img>, takes the hash from *that* HTML, and emits
    the ``{WxH}`` hint the app parses out of the markdown. Deriving without
    the probe produced a different hash for identical content, so the two
    writers overwrote each other forever — production held a notice at
    editCount 30 across exactly two alternating hashes.
    """

    OLD_HTML = "<p>옛 본문</p>"
    NEW_HTML = '<div><p>새 본문</p><p>둘째 문단</p></div>'
    IMAGE_HTML = '<div><p>새 본문</p><img src="https://example.com/poster.png"></div>'
    DIMENSIONS = {"https://example.com/poster.png": (891, 1260)}

    def _probe(self, dimensions: dict | None = None):
        """Stand in for the network image probe, for both derivations.

        Patching it identically on both sides is the point: any hash
        difference that survives is a difference in the DERIVATION, which is
        exactly what this class is about.
        """
        async def _verify(content_html, source_url):
            return ImageCheckResult(
                checked=len(dimensions or {}), dimensions=dict(dimensions or {})
            )

        return patch("skkuverse_crawler.modules.notices.stages.verify_notice_images", _verify)

    async def _crawl_would_store(self, html: str, dimensions: dict | None = None):
        """What a crawl writes for this body.

        Deliberately assembled the way the crawl does — DEFAULT_PIPELINE
        into build_notice — rather than by calling derive_content_fields.
        Using the same function on both sides would make the comparison
        tautological: it would pass no matter what either path produced.
        """
        with self._probe(dimensions):
            doc = await DEFAULT_PIPELINE.run(
                ContentDoc(raw=html),
                StageContext(
                    source_id=MOCK_DEPT["id"],
                    base_url=MOCK_DEPT["baseUrl"],
                    source_url="https://example.com/1",
                    article_no=1,
                ),
            )
        notice = build_notice(
            NoticeListItem(
                articleNo=1, title="제목", category="", author="",
                date="2026-06-17", views=0, detailPath="?articleNo=1",
            ),
            NoticeDetail(content=html, contentText="strategy가 준 텍스트", attachments=[]),
            department=MOCK_DEPT["name"],
            source_id=MOCK_DEPT["id"],
            base_url=MOCK_DEPT["baseUrl"],
            content=doc,
        )
        return ContentFields(
            content=notice.content,
            contentText=notice.contentText,
            cleanHtml=notice.cleanHtml,
            cleanMarkdown=notice.cleanMarkdown,
            contentHash=notice.contentHash,
        )

    async def _run_change(
        self, collection: FakeCollection, new_html: str = NEW_HTML, dimensions=None
    ):
        """Store a notice, then let Tier-2 see different content for it."""
        old = await self._crawl_would_store(self.OLD_HTML)
        await collection.update_one(
            {"articleNo": 1, "sourceId": "test-dept"},
            {"$set": {
                "articleNo": 1, "sourceId": "test-dept", "detailPath": "?articleNo=1",
                "sourceUrl": "https://example.com/1", "title": "제목", **old.as_set(),
            }},
            upsert=True,
        )
        notices = [{
            "articleNo": 1, "sourceId": "test-dept", "detailPath": "?articleNo=1",
            "sourceUrl": "https://example.com/1",
            "contentHash": old.contentHash, "title": "제목",
        }]
        strategy = AsyncMock()
        strategy.crawl_detail.return_value = NoticeDetail(
            content=new_html, contentText="strategy가 준 텍스트", attachments=[],
        )
        with self._probe(dimensions), patch(
            "skkuverse_crawler.plugins.mongo.update_checker.STRATEGY_MAP",
            {"skku-standard": MagicMock(return_value=strategy)},
        ):
            result = await _check_department(
                MOCK_DEPT, notices, collection, AsyncMock(), MagicMock()
            )
        return result, collection.docs[0]

    async def test_tier2_and_the_crawl_agree_on_the_hash(self):
        """The one that ends the ping-pong.

        Same body, same probe result — so the hashes must be equal. They
        were not: Tier-2 hashed dimensionless HTML, the crawl hashed HTML
        with width/height, and each kept "detecting" the other's write as a
        content change.
        """
        collection = FakeCollection()
        _, stored = await self._run_change(
            collection, new_html=self.IMAGE_HTML, dimensions=self.DIMENSIONS
        )
        crawl = await self._crawl_would_store(self.IMAGE_HTML, self.DIMENSIONS)

        assert stored["contentHash"] == crawl.contentHash

    async def test_image_dimensions_survive_a_tier2_edit(self):
        """The app parses `![{WxH}` to reserve the image's space before it
        loads. Tier-2 rewriting the markdown without it means every edited
        notice starts shifting its layout on render."""
        collection = FakeCollection()
        _, stored = await self._run_change(
            collection, new_html=self.IMAGE_HTML, dimensions=self.DIMENSIONS
        )

        assert 'width="891"' in stored["cleanHtml"]
        assert "![{891x1260}" in stored["cleanMarkdown"]

    async def test_cleanMarkdown_is_recomputed(self):
        """The symptom that started this: the app renders cleanMarkdown
        first, so leaving it stale showed the old body with no error."""
        collection = FakeCollection()
        result, stored = await self._run_change(collection)

        assert result.content_changed == 1
        assert "새 본문" in stored["cleanMarkdown"]
        assert "옛 본문" not in stored["cleanMarkdown"]

    async def test_every_content_field_moves_together(self):
        """A stored field left behind by an edit is the general shape of
        this bug, so all five are compared against what a crawl would
        write."""
        collection = FakeCollection()
        _, stored = await self._run_change(collection)
        expected = await self._crawl_would_store(self.NEW_HTML)

        for field, value in expected.as_set().items():
            assert stored[field] == value, f"{field} did not follow the edit"

    async def test_contentText_comes_from_the_sanitized_html(self):
        """Tier-2 used to store the strategy's own text. The crawl extracts
        from cleanHtml instead, which is what preserves the block newlines
        added in 2026-04."""
        collection = FakeCollection()
        _, stored = await self._run_change(collection)

        assert stored["contentText"] != "strategy가 준 텍스트"
        assert "새 본문" in stored["contentText"]
        assert "둘째 문단" in stored["contentText"]
        assert "\n" in stored["contentText"]

    async def test_oversized_content_is_dropped_not_stored(self):
        """The crawl nulls content past 5MB. Tier-2 had no guard, and
        content + cleanHtml + contentText share one 16MB document limit."""
        collection = FakeCollection()
        huge = "<p>" + ("가" * 2_000_000) + "</p>"  # ~6MB as UTF-8
        _, stored = await self._run_change(collection, new_html=huge)

        assert stored["cleanHtml"] is None
        assert stored["content"] is None
        assert stored["cleanMarkdown"] is None
        assert stored["contentHash"] is None


class TestContentVanished:
    """A body that sanitises to nothing is an anomaly, not an edit."""

    STORED_HTML = "<p>본문이 있었다</p>"

    async def _run(self, new_html: str):
        collection = FakeCollection()
        async def _verify(content_html, source_url):
            return ImageCheckResult()
        with patch("skkuverse_crawler.modules.notices.stages.verify_notice_images", _verify):
            old = await derive_content_fields(
                self.STORED_HTML, base_url=MOCK_DEPT["baseUrl"]
            )
            await collection.update_one(
                {"articleNo": 1, "sourceId": "test-dept"},
                {"$set": {
                    "articleNo": 1, "sourceId": "test-dept", "detailPath": "?articleNo=1",
                    "title": "제목", **old.as_set(),
                }},
                upsert=True,
            )
            notices = [{
                "articleNo": 1, "sourceId": "test-dept", "detailPath": "?articleNo=1",
                "contentHash": old.contentHash, "title": "제목",
            }]
            strategy = AsyncMock()
            strategy.crawl_detail.return_value = NoticeDetail(
                content=new_html, contentText="", attachments=[],
            )
            with patch(
                "skkuverse_crawler.plugins.mongo.update_checker.STRATEGY_MAP",
                {"skku-standard": MagicMock(return_value=strategy)},
            ):
                result = await _check_department(
                    MOCK_DEPT, notices, collection, AsyncMock(), MagicMock()
                )
        return result, collection.docs[0]

    @pytest.mark.parametrize(
        "empty_body",
        [
            "<div></div>",
            "<p>&nbsp;</p>",
            "   ",
            '<div class="w3eden"><p>download</p></div>',  # WPDM block, stripped whole
        ],
    )
    async def test_an_emptied_body_does_not_blank_the_stored_one(self, empty_body):
        """Sanitising to None used to read as "content changed", which wrote
        None over every content field — including cleanMarkdown, the app's
        first-choice render source. A soft error page would have erased the
        notice."""
        result, stored = await self._run(empty_body)

        assert result.content_vanished == 1
        assert result.content_changed == 0
        assert stored["cleanHtml"] == "<p>본문이 있었다</p>"
        assert "본문이 있었다" in stored["cleanMarkdown"]

    async def test_it_is_counted_so_a_mass_emptying_is_visible(self):
        """Silently skipping would hide a source that started serving error
        pages to every request."""
        result, _ = await self._run("<div></div>")
        assert result.content_vanished == 1
