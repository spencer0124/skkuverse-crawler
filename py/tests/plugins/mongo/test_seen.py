from __future__ import annotations

from unittest.mock import MagicMock

from skkuverse_crawler.core.ports import SeenRecord
from skkuverse_crawler.plugins.mongo.seen import MongoSeenIndex


class TestMongoSeenIndexLookup:
    """Ports the dedup.find_existing_meta assertions onto the adapter."""

    async def test_projection_includes_content_hash(self, mock_collection):
        async def empty_cursor():
            return
            yield  # make it an async generator

        mock_collection.find = MagicMock(return_value=empty_cursor())

        await MongoSeenIndex(mock_collection).lookup("dept-1", [1, 2])

        call_args = mock_collection.find.call_args
        assert call_args[0][0] == {"sourceId": "dept-1", "articleNo": {"$in": [1, 2]}}
        projection = call_args[0][1]
        assert "contentHash" in projection
        assert projection["contentHash"] == 1

    async def test_returns_seen_records(self, mock_collection):
        async def cursor_with_doc():
            yield {"articleNo": 1, "title": "test", "date": "2026-03-01", "contentHash": "abc"}

        mock_collection.find = MagicMock(return_value=cursor_with_doc())

        result = await MongoSeenIndex(mock_collection).lookup("dept-1", [1])
        assert result[1] == SeenRecord(
            article_no=1, title="test", date="2026-03-01", content_hash="abc"
        )

    async def test_content_hash_none_when_missing(self, mock_collection):
        async def cursor_with_doc():
            yield {"articleNo": 1, "title": "test", "date": "2026-03-01"}

        mock_collection.find = MagicMock(return_value=cursor_with_doc())

        result = await MongoSeenIndex(mock_collection).lookup("dept-1", [1])
        assert result[1].content_hash is None
