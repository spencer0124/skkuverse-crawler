from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from bson import ObjectId

from skkuverse_crawler.notices_summary.query import (
    find_stale_summaries,
    find_unsummarized,
)


def _make_doc(**overrides) -> dict:
    defaults = {
        "_id": ObjectId(),
        "articleNo": 1,
        "sourceId": "test-dept",
        "title": "테스트 공지",
        "category": "일반",
        "contentText": "본문 텍스트",
        "contentHash": "abc123",
    }
    defaults.update(overrides)
    return defaults


def _mock_collection_with_docs(docs: list[dict]):
    """Create a mock collection whose .find() returns an async iterator."""
    coll = MagicMock()

    async def async_iter():
        for d in docs:
            yield d

    chain = MagicMock()
    chain.sort = MagicMock(return_value=chain)
    chain.limit = MagicMock(return_value=async_iter())
    coll.find = MagicMock(return_value=chain)
    return coll


class TestFindUnsummarized:
    async def test_returns_docs(self):
        doc = _make_doc()
        coll = _mock_collection_with_docs([doc])

        result = await find_unsummarized(coll, batch_size=10)

        assert len(result) == 1
        assert result[0]["articleNo"] == 1

    async def test_query_uses_not_gte_for_failures(self):
        coll = _mock_collection_with_docs([])

        await find_unsummarized(coll, batch_size=10)

        query = coll.find.call_args[0][0]
        assert query["summaryFailures"] == {"$not": {"$gte": 3}}

    async def test_query_excludes_null_content(self):
        coll = _mock_collection_with_docs([])

        await find_unsummarized(coll, batch_size=10)

        query = coll.find.call_args[0][0]
        assert query["contentText"] == {"$nin": [None, ""]}

    async def test_empty_result(self):
        coll = _mock_collection_with_docs([])
        result = await find_unsummarized(coll, batch_size=10)
        assert result == []


class TestFindStaleSummaries:
    async def test_returns_stale_docs(self):
        doc = _make_doc(
            summaryContentHash="old-hash",
            contentHash="new-hash",
            summaryAt=datetime.now(UTC),
        )
        coll = _mock_collection_with_docs([doc])

        result = await find_stale_summaries(coll, batch_size=10)

        assert len(result) == 1

    async def test_query_uses_expr_ne(self):
        coll = _mock_collection_with_docs([])

        await find_stale_summaries(coll, batch_size=10)

        query = coll.find.call_args[0][0]
        assert query["$expr"] == {"$ne": ["$summaryContentHash", "$contentHash"]}

    async def test_query_includes_failure_check(self):
        coll = _mock_collection_with_docs([])

        await find_stale_summaries(coll, batch_size=10)

        query = coll.find.call_args[0][0]
        assert query["summaryFailures"] == {"$not": {"$gte": 3}}
