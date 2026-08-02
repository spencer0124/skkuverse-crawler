"""Tests for the dispatch-related additions in processor.py.

Covers:
* `_summarize_one` writes both `summaryAt` AND `aiSummaryAt` on success.
* `_summarize_one` writes neither on AI failure (only `$inc` summaryFailures).
* `run_summary_batch` calls `notify_cycle_complete` exactly once at the end.
* Empty cycle (0 summarized + 0 stale) still pings — uniform contract.
* Exceptions from `notify_cycle_complete` are swallowed by the batch.
* `cycle_id` passed to notify is bound at function entry (so retries inherit it).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId

from skkuverse_crawler.plugins.ai_summary.processor import run_summary_batch

SAMPLE_AI_RESPONSE = {
    "oneLiner": "한 줄 요약",
    "summary": "전체 요약",
    "type": "informational",
    "periods": [],
    "locations": [],
    "details": {"target": None, "action": None, "host": None, "impact": None},
    "model": "openai/gpt-4.1-mini",
}


def _make_doc(**overrides) -> dict:
    defaults = {
        "_id": ObjectId(),
        "articleNo": 1,
        "sourceId": "test-dept",
        "title": "테스트 공지",
        "category": "일반",
        "contentText": "본문",
        "contentHash": "hash-1",
    }
    defaults.update(overrides)
    return defaults


def _patches():
    """Common decorator stack used by every test in this module."""

    def wrap(fn):
        return (
            patch("skkuverse_crawler.plugins.ai_summary.processor.notify_cycle_complete")(
                patch("skkuverse_crawler.plugins.ai_summary.processor.find_stale_summaries")(
                    patch("skkuverse_crawler.plugins.ai_summary.processor.find_unsummarized")(
                        patch("skkuverse_crawler.plugins.ai_summary.processor.ensure_summary_indexes")(
                            patch("skkuverse_crawler.plugins.ai_summary.processor.AiClient")(
                                patch("skkuverse_crawler.plugins.ai_summary.processor.get_db")(
                                    fn
                                )
                            )
                        )
                    )
                )
            )
        )

    return wrap


def _setup_db_and_ai(mock_get_db, mock_ai_cls, ai_returns=SAMPLE_AI_RESPONSE):
    mock_collection = AsyncMock()
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    mock_get_db.return_value = mock_db

    mock_client = AsyncMock()
    mock_client.summarize.return_value = ai_returns
    mock_ai_cls.return_value = mock_client
    return mock_collection, mock_client


class TestAiSummaryAtField:
    @_patches()
    async def test_set_on_success_alongside_summary_at(
        self,
        mock_get_db,
        mock_ai_cls,
        mock_indexes,
        mock_find,
        mock_find_stale,
        mock_notify,
    ):
        doc = _make_doc()
        mock_collection, _ = _setup_db_and_ai(mock_get_db, mock_ai_cls)
        mock_indexes.return_value = None
        mock_find.return_value = [doc]
        mock_find_stale.return_value = []
        mock_notify.return_value = True

        await run_summary_batch(batch_size=10, delay_seconds=0)

        update_doc = mock_collection.update_one.call_args[0][1]
        assert "aiSummaryAt" in update_doc["$set"]
        assert "summaryAt" in update_doc["$set"]
        # Both must be datetime instances; they share the same value semantically
        # but are written as two distinct fields so future divergence is safe.
        from datetime import datetime
        assert isinstance(update_doc["$set"]["aiSummaryAt"], datetime)
        assert isinstance(update_doc["$set"]["summaryAt"], datetime)

    @_patches()
    async def test_neither_set_on_failure(
        self,
        mock_get_db,
        mock_ai_cls,
        mock_indexes,
        mock_find,
        mock_find_stale,
        mock_notify,
    ):
        doc = _make_doc()
        mock_collection, mock_client = _setup_db_and_ai(mock_get_db, mock_ai_cls)
        mock_client.summarize.side_effect = Exception("AI down")
        mock_indexes.return_value = None
        mock_find.return_value = [doc]
        mock_find_stale.return_value = []
        mock_notify.return_value = True

        await run_summary_batch(batch_size=10, delay_seconds=0)

        # On failure path the only update is $inc summaryFailures.
        failure_call = mock_collection.update_one.call_args[0][1]
        assert "$inc" in failure_call
        assert "summaryFailures" in failure_call["$inc"]
        # No $set with aiSummaryAt should leak through.
        assert "$set" not in failure_call


class TestNotifyCycleComplete:
    @_patches()
    async def test_called_once_at_end(
        self,
        mock_get_db,
        mock_ai_cls,
        mock_indexes,
        mock_find,
        mock_find_stale,
        mock_notify,
    ):
        _setup_db_and_ai(mock_get_db, mock_ai_cls)
        mock_indexes.return_value = None
        mock_find.return_value = [_make_doc(), _make_doc(articleNo=2)]
        mock_find_stale.return_value = []
        mock_notify.return_value = True

        await run_summary_batch(batch_size=10, delay_seconds=0)
        assert mock_notify.call_count == 1

    @_patches()
    async def test_called_even_on_empty_cycle(
        self,
        mock_get_db,
        mock_ai_cls,
        mock_indexes,
        mock_find,
        mock_find_stale,
        mock_notify,
    ):
        _setup_db_and_ai(mock_get_db, mock_ai_cls)
        mock_indexes.return_value = None
        mock_find.return_value = []
        mock_find_stale.return_value = []
        mock_notify.return_value = True

        await run_summary_batch(batch_size=10, delay_seconds=0)
        assert mock_notify.call_count == 1

    @_patches()
    async def test_passes_cycle_id_and_source(
        self,
        mock_get_db,
        mock_ai_cls,
        mock_indexes,
        mock_find,
        mock_find_stale,
        mock_notify,
    ):
        _setup_db_and_ai(mock_get_db, mock_ai_cls)
        mock_indexes.return_value = None
        mock_find.return_value = []
        mock_find_stale.return_value = []
        mock_notify.return_value = True

        await run_summary_batch(batch_size=10, delay_seconds=0)
        kwargs = mock_notify.call_args.kwargs
        assert kwargs["source"] == "summary"
        # cycle_id is uuid4()[:8] — 8 hex chars
        assert isinstance(kwargs["cycle_id"], str)
        assert len(kwargs["cycle_id"]) == 8
        assert all(c in "0123456789abcdef" for c in kwargs["cycle_id"])
        from datetime import datetime
        assert isinstance(kwargs["crawled_at"], datetime)

    @_patches()
    async def test_unique_cycle_id_per_invocation(
        self,
        mock_get_db,
        mock_ai_cls,
        mock_indexes,
        mock_find,
        mock_find_stale,
        mock_notify,
    ):
        _setup_db_and_ai(mock_get_db, mock_ai_cls)
        mock_indexes.return_value = None
        mock_find.return_value = []
        mock_find_stale.return_value = []
        mock_notify.return_value = True

        await run_summary_batch(batch_size=10, delay_seconds=0)
        await run_summary_batch(batch_size=10, delay_seconds=0)
        assert mock_notify.call_count == 2
        ids = [c.kwargs["cycle_id"] for c in mock_notify.call_args_list]
        assert ids[0] != ids[1]

    @_patches()
    async def test_exception_is_swallowed(
        self,
        mock_get_db,
        mock_ai_cls,
        mock_indexes,
        mock_find,
        mock_find_stale,
        mock_notify,
    ):
        _setup_db_and_ai(mock_get_db, mock_ai_cls)
        mock_indexes.return_value = None
        mock_find.return_value = []
        mock_find_stale.return_value = []
        # notify_cycle_complete should never raise, but defense in depth:
        mock_notify.side_effect = RuntimeError("boom")

        # Must NOT propagate.
        result = await run_summary_batch(batch_size=10, delay_seconds=0)
        assert result["errors"] == 0  # batch result not affected by ping outcome
