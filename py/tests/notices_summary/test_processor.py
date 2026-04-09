from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId

from skkuverse_crawler.notices_summary.processor import run_summary_batch

SAMPLE_AI_RESPONSE = {
    "oneLiner": "4/30까지 등록금 납부",
    "summary": "등록금 납부 안내입니다.",
    "type": "action_required",
    "startDate": None,
    "endDate": "2026-04-30",
    "startTime": None,
    "endTime": None,
    "details": {"target": None, "action": "등록금 납부"},
    "model": "openai/gpt-4.1-mini",
}


def _make_doc(**overrides) -> dict:
    defaults = {
        "_id": ObjectId(),
        "articleNo": 1,
        "sourceDeptId": "test-dept",
        "title": "테스트 공지",
        "category": "일반",
        "contentText": "본문 텍스트",
        "contentHash": "abc123",
    }
    defaults.update(overrides)
    return defaults


class TestRunSummaryBatch:
    @patch("skkuverse_crawler.notices_summary.processor.find_stale_summaries")
    @patch("skkuverse_crawler.notices_summary.processor.find_unsummarized")
    @patch("skkuverse_crawler.notices_summary.processor.ensure_summary_indexes")
    @patch("skkuverse_crawler.notices_summary.processor.AiClient")
    @patch("skkuverse_crawler.notices_summary.processor.get_db")
    async def test_summarizes_unsummarized_docs(
        self, mock_get_db, mock_ai_cls, mock_indexes, mock_find, mock_find_stale,
    ):
        doc = _make_doc()

        # DB mock
        mock_collection = AsyncMock()
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        mock_get_db.return_value = mock_db

        # AI client mock
        mock_client = AsyncMock()
        mock_client.summarize.return_value = SAMPLE_AI_RESPONSE
        mock_ai_cls.return_value = mock_client

        mock_indexes.return_value = None
        mock_find.return_value = [doc]
        mock_find_stale.return_value = []

        result = await run_summary_batch(batch_size=10, delay_seconds=0)

        assert result["summarized"] == 1
        assert result["errors"] == 0
        mock_client.summarize.assert_called_once_with(
            title="테스트 공지", category="일반", clean_text="본문 텍스트",
        )
        mock_collection.update_one.assert_called_once()
        update_doc = mock_collection.update_one.call_args[0][1]
        assert update_doc["$set"]["summary"] == "등록금 납부 안내입니다."
        assert update_doc["$set"]["summaryFailures"] == 0

    @patch("skkuverse_crawler.notices_summary.processor.find_stale_summaries")
    @patch("skkuverse_crawler.notices_summary.processor.find_unsummarized")
    @patch("skkuverse_crawler.notices_summary.processor.ensure_summary_indexes")
    @patch("skkuverse_crawler.notices_summary.processor.AiClient")
    @patch("skkuverse_crawler.notices_summary.processor.get_db")
    async def test_increments_failures_on_error(
        self, mock_get_db, mock_ai_cls, mock_indexes, mock_find, mock_find_stale,
    ):
        doc = _make_doc()

        mock_collection = AsyncMock()
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        mock_get_db.return_value = mock_db

        mock_client = AsyncMock()
        mock_client.summarize.side_effect = Exception("API error")
        mock_ai_cls.return_value = mock_client

        mock_indexes.return_value = None
        mock_find.return_value = [doc]
        mock_find_stale.return_value = []

        result = await run_summary_batch(batch_size=10, delay_seconds=0)

        assert result["errors"] == 1
        assert result["summarized"] == 0

        # Check $inc summaryFailures
        failure_call = mock_collection.update_one.call_args[0][1]
        assert failure_call["$inc"]["summaryFailures"] == 1

    @patch("skkuverse_crawler.notices_summary.processor.find_stale_summaries")
    @patch("skkuverse_crawler.notices_summary.processor.find_unsummarized")
    @patch("skkuverse_crawler.notices_summary.processor.ensure_summary_indexes")
    @patch("skkuverse_crawler.notices_summary.processor.AiClient")
    @patch("skkuverse_crawler.notices_summary.processor.get_db")
    async def test_handles_stale_summaries(
        self, mock_get_db, mock_ai_cls, mock_indexes, mock_find, mock_find_stale,
    ):
        stale_doc = _make_doc(articleNo=2, contentHash="new-hash")

        mock_collection = AsyncMock()
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        mock_get_db.return_value = mock_db

        mock_client = AsyncMock()
        mock_client.summarize.return_value = SAMPLE_AI_RESPONSE
        mock_ai_cls.return_value = mock_client

        mock_indexes.return_value = None
        mock_find.return_value = []
        mock_find_stale.return_value = [stale_doc]

        result = await run_summary_batch(batch_size=10, delay_seconds=0)

        assert result["stale_updated"] == 1
        assert result["summarized"] == 0

    @patch("skkuverse_crawler.notices_summary.processor.find_stale_summaries")
    @patch("skkuverse_crawler.notices_summary.processor.find_unsummarized")
    @patch("skkuverse_crawler.notices_summary.processor.ensure_summary_indexes")
    @patch("skkuverse_crawler.notices_summary.processor.AiClient")
    @patch("skkuverse_crawler.notices_summary.processor.get_db")
    async def test_empty_batch(
        self, mock_get_db, mock_ai_cls, mock_indexes, mock_find, mock_find_stale,
    ):
        mock_collection = AsyncMock()
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        mock_get_db.return_value = mock_db

        mock_client = AsyncMock()
        mock_ai_cls.return_value = mock_client

        mock_indexes.return_value = None
        mock_find.return_value = []
        mock_find_stale.return_value = []

        result = await run_summary_batch(batch_size=10, delay_seconds=0)

        assert result["summarized"] == 0
        assert result["stale_updated"] == 0
        assert result["errors"] == 0
        mock_client.summarize.assert_not_called()

    @patch("skkuverse_crawler.notices_summary.processor.find_stale_summaries")
    @patch("skkuverse_crawler.notices_summary.processor.find_unsummarized")
    @patch("skkuverse_crawler.notices_summary.processor.ensure_summary_indexes")
    @patch("skkuverse_crawler.notices_summary.processor.AiClient")
    @patch("skkuverse_crawler.notices_summary.processor.get_db")
    async def test_handles_missing_response_fields(
        self, mock_get_db, mock_ai_cls, mock_indexes, mock_find, mock_find_stale,
    ):
        doc = _make_doc()

        mock_collection = AsyncMock()
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        mock_get_db.return_value = mock_db

        mock_client = AsyncMock()
        mock_client.summarize.return_value = {"oneLiner": "test"}  # missing summary, type
        mock_ai_cls.return_value = mock_client

        mock_indexes.return_value = None
        mock_find.return_value = [doc]
        mock_find_stale.return_value = []

        result = await run_summary_batch(batch_size=10, delay_seconds=0)

        assert result["errors"] == 1
        assert result["summarized"] == 0
        failure_call = mock_collection.update_one.call_args[0][1]
        assert failure_call["$inc"]["summaryFailures"] == 1
