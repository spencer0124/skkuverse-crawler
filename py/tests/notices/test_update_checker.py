from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from skkuverse_crawler.notices.models import NoticeDetail
from skkuverse_crawler.notices.update_checker import _check_department


MOCK_DEPT = {
    "id": "test-dept",
    "name": "테스트학과",
    "baseUrl": "https://example.com",
    "strategy": "skku-standard",
}


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
            "skkuverse_crawler.notices.update_checker.compute_content_hash",
            return_value="existing_hash",
        ), patch(
            "skkuverse_crawler.notices.update_checker.clean_html",
            return_value="<p>본문</p>",
        ), patch(
            "skkuverse_crawler.notices.update_checker.STRATEGY_MAP",
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
            "skkuverse_crawler.notices.update_checker.compute_content_hash",
            return_value="new_hash",
        ), patch(
            "skkuverse_crawler.notices.update_checker.clean_html",
            return_value="<p>새 본문</p>",
        ), patch(
            "skkuverse_crawler.notices.update_checker.STRATEGY_MAP",
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
            "skkuverse_crawler.notices.update_checker.compute_content_hash",
            return_value="new_hash",
        ), patch(
            "skkuverse_crawler.notices.update_checker.clean_html",
            return_value="<p>본문</p>",
        ), patch(
            "skkuverse_crawler.notices.update_checker.STRATEGY_MAP",
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
            "skkuverse_crawler.notices.update_checker.STRATEGY_MAP",
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
            "skkuverse_crawler.notices.update_checker.compute_content_hash",
            return_value="h2",  # same hash → no update
        ), patch(
            "skkuverse_crawler.notices.update_checker.clean_html",
            return_value="<p>ok</p>",
        ), patch(
            "skkuverse_crawler.notices.update_checker.STRATEGY_MAP",
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
            "skkuverse_crawler.notices.update_checker.compute_content_hash",
            side_effect=varying_hash,
        ), patch(
            "skkuverse_crawler.notices.update_checker.clean_html",
            return_value="<p>새 본문</p>",
        ), patch(
            "skkuverse_crawler.notices.update_checker.STRATEGY_MAP",
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
            "skkuverse_crawler.notices.update_checker.compute_content_hash",
            side_effect=half_changed_hash,
        ), patch(
            "skkuverse_crawler.notices.update_checker.clean_html",
            return_value="<p>본문</p>",
        ), patch(
            "skkuverse_crawler.notices.update_checker.STRATEGY_MAP",
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
            "skkuverse_crawler.notices.update_checker.compute_content_hash",
            return_value="same",
        ), patch(
            "skkuverse_crawler.notices.update_checker.clean_html",
            return_value="<p>본문</p>",
        ), patch(
            "skkuverse_crawler.notices.update_checker.STRATEGY_MAP",
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
            "skkuverse_crawler.notices.update_checker.STRATEGY_MAP",
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
            "skkuverse_crawler.notices.update_checker.STRATEGY_MAP",
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
            "skkuverse_crawler.notices.update_checker.compute_content_hash",
            return_value="same",
        ), patch(
            "skkuverse_crawler.notices.update_checker.clean_html",
            return_value="<p>본문</p>",
        ), patch(
            "skkuverse_crawler.notices.update_checker.STRATEGY_MAP",
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
            "skkuverse_crawler.notices.update_checker.compute_content_hash",
            side_effect=match_hash,
        ), patch(
            "skkuverse_crawler.notices.update_checker.clean_html",
            return_value="<p>ok</p>",
        ), patch(
            "skkuverse_crawler.notices.update_checker.STRATEGY_MAP",
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
        from skkuverse_crawler.notices.constants import SERVICE_START_DATE
        # window cutoff가 floor date보다 이전 → floor date 사용
        assert max(SERVICE_START_DATE, "2026-03-01") == SERVICE_START_DATE

    def test_window_wins_when_narrower(self):
        from skkuverse_crawler.notices.constants import SERVICE_START_DATE
        # window cutoff가 floor date보다 이후 → window cutoff 사용
        assert max(SERVICE_START_DATE, "2026-05-01") == "2026-05-01"
