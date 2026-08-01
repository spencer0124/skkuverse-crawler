from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from unittest.mock import MagicMock

from skkuverse_crawler.core.events import (
    ChangeInfo,
    ContentRefreshed,
    CrawlEvent,
    NoticeCrawled,
    NoticeUnchanged,
)
from skkuverse_crawler.core.ports import DetailRef, Outcome, SourceSpec
from skkuverse_crawler.modules.notices.models import Notice
from skkuverse_crawler.plugins.mongo.sink import MongoSink


def _make_notice(**overrides) -> Notice:
    defaults = dict(
        articleNo=1,
        title="테스트 공지",
        category="일반",
        author="관리자",
        department="테스트학과",
        date="2026-03-01",
        views=10,
        content="<p>본문</p>",
        contentText="본문",
        cleanHtml="<p>본문</p>",
        attachments=[],
        sourceUrl="https://example.com/1",
        detailPath="?articleNo=1",
        sourceId="test-dept",
        crawledAt=datetime.now(timezone.utc),
        contentHash="abc123",
    )
    defaults.update(overrides)
    return Notice(**defaults)


def _crawled(notice: Notice, change: ChangeInfo | None = None) -> NoticeCrawled:
    return NoticeCrawled(source_id=notice.sourceId, notice=notice, change=change)


def _change(**overrides) -> ChangeInfo:
    defaults = dict(
        old_hash="old",
        new_hash="new",
        old_title="Original title",
        new_title="Edited title",
        title_changed=True,
        content_changed=True,
    )
    defaults.update(overrides)
    return ChangeInfo(**defaults)


@dataclasses.dataclass(frozen=True)
class _UnknownFutureEvent(CrawlEvent):
    payload: str = "surprise"


class TestUpsertPath:
    """NoticeCrawled(change=None) — dedup.upsert_notice assertions ported."""

    async def test_set_excludes_edit_fields(self, mock_collection):
        mock_collection.update_one.return_value = MagicMock(upserted_id="new")

        await MongoSink(mock_collection).accept(_crawled(_make_notice()))

        update_doc = mock_collection.update_one.call_args[0][1]
        assert "editHistory" not in update_doc["$set"]
        assert "editCount" not in update_doc["$set"]
        assert "editHistory" in update_doc["$setOnInsert"]
        assert "editCount" in update_doc["$setOnInsert"]

    async def test_returns_inserted_when_upserted(self, mock_collection):
        mock_collection.update_one.return_value = MagicMock(upserted_id="new-id")
        outcome = await MongoSink(mock_collection).accept(_crawled(_make_notice()))
        assert outcome is Outcome.INSERTED

    async def test_returns_updated_when_existing(self, mock_collection):
        mock_collection.update_one.return_value = MagicMock(upserted_id=None)
        outcome = await MongoSink(mock_collection).accept(_crawled(_make_notice()))
        assert outcome is Outcome.UPDATED


class TestHistoryPath:
    """NoticeCrawled(change=…) — dedup.update_with_history assertions ported,
    plus the edit_entry construction that moved in from the orchestrator."""

    async def test_push_edit_entry_with_slice(self, mock_collection):
        await MongoSink(mock_collection).accept(_crawled(_make_notice(), _change()))

        update_doc = mock_collection.update_one.call_args[0][1]
        push = update_doc["$push"]["editHistory"]
        assert push["$slice"] == -20
        assert len(push["$each"]) == 1
        assert update_doc["$inc"]["editCount"] == 1

    async def test_edit_entry_shape(self, mock_collection):
        await MongoSink(mock_collection).accept(_crawled(_make_notice(), _change()))

        entry = mock_collection.update_one.call_args[0][1]["$push"]["editHistory"]["$each"][0]
        assert isinstance(entry["detectedAt"], datetime)
        assert entry["oldHash"] == "old"
        assert entry["newHash"] == "new"
        assert entry["oldTitle"] == "Original title"
        assert entry["newTitle"] == "Edited title"
        assert entry["titleChanged"] is True
        assert entry["contentChanged"] is True
        assert entry["source"] == "tier1"

    async def test_set_excludes_edit_fields(self, mock_collection):
        await MongoSink(mock_collection).accept(_crawled(_make_notice(), _change()))

        update_doc = mock_collection.update_one.call_args[0][1]
        assert "editHistory" not in update_doc["$set"]
        assert "editCount" not in update_doc["$set"]

    async def test_no_upsert(self, mock_collection):
        """History updates are existing-doc only — never upsert=True."""
        await MongoSink(mock_collection).accept(_crawled(_make_notice(), _change()))

        call_kwargs = mock_collection.update_one.call_args.kwargs
        assert call_kwargs.get("upsert", False) is False

    async def test_returns_updated(self, mock_collection):
        outcome = await MongoSink(mock_collection).accept(
            _crawled(_make_notice(), _change())
        )
        assert outcome is Outcome.UPDATED


class TestTouchBufferAndFlush:
    def _unchanged(self, article_no: int, views: int = 5) -> NoticeUnchanged:
        return NoticeUnchanged(source_id="test-dept", article_no=article_no, views=views)

    async def test_accept_buffers_without_writing(self, mock_collection):
        sink = MongoSink(mock_collection)
        assert await sink.accept(self._unchanged(1)) is None
        mock_collection.update_one.assert_not_awaited()
        mock_collection.bulk_write.assert_not_awaited()

    async def test_flush_emits_single_unordered_bulk_write(self, mock_collection):
        sink = MongoSink(mock_collection)
        await sink.accept(self._unchanged(1, views=3))
        await sink.accept(self._unchanged(2, views=7))

        await sink.flush()

        assert mock_collection.bulk_write.await_count == 1
        args, kwargs = mock_collection.bulk_write.call_args
        assert kwargs == {"ordered": False}
        ops = args[0]
        assert len(ops) == 2
        # pymongo UpdateOne internals — same access pattern as FakeCollection
        assert ops[0]._filter == {"articleNo": 1, "sourceId": "test-dept"}
        assert ops[0]._doc["$set"]["views"] == 3
        assert isinstance(ops[0]._doc["$set"]["crawledAt"], datetime)

    async def test_empty_flush_is_noop(self, mock_collection):
        await MongoSink(mock_collection).flush()
        mock_collection.bulk_write.assert_not_awaited()

    async def test_flush_clears_buffer(self, mock_collection):
        sink = MongoSink(mock_collection)
        await sink.accept(self._unchanged(1))
        await sink.flush()
        await sink.flush()
        assert mock_collection.bulk_write.await_count == 1


class TestPrepare:
    async def test_creates_both_indexes_in_order(self, mock_collection):
        await MongoSink(mock_collection).prepare(SourceSpec(source_id="a"))

        assert mock_collection.create_index.await_count == 2
        first, second = mock_collection.create_index.await_args_list
        assert first[0][0] == [("articleNo", 1), ("sourceId", 1)]
        assert first[1] == {"unique": True}
        assert second[0][0] == [("sourceId", 1), ("date", -1)]

    async def test_idempotent_across_sources(self, mock_collection):
        sink = MongoSink(mock_collection)
        await sink.prepare(SourceSpec(source_id="a"))
        await sink.prepare(SourceSpec(source_id="b"))
        assert mock_collection.create_index.await_count == 2


class TestContentRefreshed:
    async def test_reproduces_backfill_update(self, mock_collection):
        fields = {
            "content": "<p>x</p>",
            "contentText": "x",
            "cleanHtml": "<p>x</p>",
            "cleanMarkdown": "x",
            "contentHash": "h",
            "attachments": [],
        }
        event = ContentRefreshed(
            source_id="test-dept",
            ref=DetailRef(article_no=9, detail_path="?articleNo=9"),
            fields=fields,
        )

        outcome = await MongoSink(mock_collection).accept(event)

        assert outcome is Outcome.UPDATED
        args = mock_collection.update_one.call_args[0]
        assert args[0] == {"articleNo": 9, "sourceId": "test-dept"}
        set_doc = args[1]["$set"]
        assert set_doc["content"] == "<p>x</p>"
        assert set_doc["contentHash"] == "h"
        assert isinstance(set_doc["crawledAt"], datetime)
        assert sorted(set_doc) == sorted([*fields, "crawledAt"])


class TestTolerantReader:
    async def test_unknown_event_ignored_without_touching_db(self, mock_collection):
        sink = MongoSink(mock_collection)
        assert await sink.accept(_UnknownFutureEvent(source_id="test")) is None
        mock_collection.update_one.assert_not_awaited()
        mock_collection.bulk_write.assert_not_awaited()
        mock_collection.create_index.assert_not_awaited()
