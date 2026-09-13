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

    async def test_projection_includes_views(self, mock_collection):
        """skkuverse#52 — the caller compares this against the freshly
        scraped count to decide whether the row is worth writing at all.
        Drop it from the projection and every stored view becomes None,
        which compares unequal to any observed count: the touch comes back
        in full, silently, with the tests still green everywhere else."""

        async def empty_cursor():
            return
            yield

        mock_collection.find = MagicMock(return_value=empty_cursor())
        await MongoSeenIndex(mock_collection).lookup("dept-1", [1])
        assert mock_collection.find.call_args[0][1]["views"] == 1

    async def test_views_carried_through(self, mock_collection):
        async def cursor_with_doc():
            yield {"articleNo": 1, "title": "t", "date": "2026-03-01", "views": 77}

        mock_collection.find = MagicMock(return_value=cursor_with_doc())
        result = await MongoSeenIndex(mock_collection).lookup("dept-1", [1])
        assert result[1].views == 77

    async def test_views_none_when_missing(self, mock_collection):
        """None, not 0. A document written before the field existed must
        compare unequal to any observed count so it gets written once and
        backfilled — reading absence as 0 would freeze it at 0 forever for
        any source whose list page reports no view counter."""

        async def cursor_with_doc():
            yield {"articleNo": 1, "title": "t", "date": "2026-03-01"}

        mock_collection.find = MagicMock(return_value=cursor_with_doc())
        result = await MongoSeenIndex(mock_collection).lookup("dept-1", [1])
        assert result[1].views is None
