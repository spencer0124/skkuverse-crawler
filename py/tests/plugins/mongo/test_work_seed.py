from __future__ import annotations

from unittest.mock import MagicMock

from skkuverse_crawler.core.ports import DetailRef
from skkuverse_crawler.plugins.mongo.work_seed import MongoWorkSeed


class TestMongoWorkSeed:
    async def test_queries_null_or_empty_content(self, mock_collection):
        async def empty_cursor():
            return
            yield

        mock_collection.find = MagicMock(return_value=empty_cursor())

        await MongoWorkSeed(mock_collection).pending_refs("dept-1")

        call_args = mock_collection.find.call_args
        assert call_args[0][0] == {
            "sourceId": "dept-1",
            "$or": [{"content": None}, {"content": ""}],
        }
        assert call_args[0][1] == {"articleNo": 1, "detailPath": 1}

    async def test_returns_detail_refs_with_path_default(self, mock_collection):
        async def cursor_with_docs():
            yield {"articleNo": 1, "detailPath": "?articleNo=1"}
            yield {"articleNo": 2}  # missing detailPath -> ""

        mock_collection.find = MagicMock(return_value=cursor_with_docs())

        refs = await MongoWorkSeed(mock_collection).pending_refs("dept-1")
        assert refs == [
            DetailRef(article_no=1, detail_path="?articleNo=1"),
            DetailRef(article_no=2, detail_path=""),
        ]
