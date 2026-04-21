from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from skkuverse_crawler.notices.dedup import (
    find_existing_meta,
    has_changed,
    update_with_history,
    upsert_notice,
)
from skkuverse_crawler.notices.models import Notice, NoticeListItem


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
        sourceDeptId="test-dept",
        crawledAt=datetime.now(timezone.utc),
        contentHash="abc123",
    )
    defaults.update(overrides)
    return Notice(**defaults)


def _make_list_item(**overrides) -> NoticeListItem:
    defaults = dict(
        articleNo=1,
        title="테스트 공지",
        category="일반",
        author="관리자",
        date="2026-03-01",
        views=0,
        detailPath="?articleNo=1",
    )
    defaults.update(overrides)
    return NoticeListItem(**defaults)


class TestHasChanged:
    def test_identical_title_and_date_not_changed(self):
        item = _make_list_item(title="Hello", date="2026-03-01")
        existing = {"title": "Hello", "date": "2026-03-01"}
        assert has_changed(item, existing) is False

    def test_date_differs_is_changed(self):
        item = _make_list_item(title="Hello", date="2026-03-02")
        existing = {"title": "Hello", "date": "2026-03-01"}
        assert has_changed(item, existing) is True

    def test_truncated_title_with_ellipsis_matches_prefix(self):
        item = _make_list_item(title="Very long announcemen...", date="2026-03-01")
        existing = {"title": "Very long announcement about stuff", "date": "2026-03-01"}
        assert has_changed(item, existing) is False

    def test_truncated_title_with_ufffd_before_ellipsis(self):
        # cal.skku.edu style: source byte-truncates title mid multi-byte
        # character, resulting in a trailing U+FFFD before "...".
        item = _make_list_item(
            title="[IBK기업은행] 2026년 전문·일반계약직 및 전문준정규직 채용�...",
            date="2026-04-20",
        )
        existing = {
            "title": "[IBK기업은행] 2026년 전문·일반계약직 및 전문준정규직 채용공고 (~5/4, 10:00)",
            "date": "2026-04-20",
        }
        assert has_changed(item, existing) is False

    def test_truncated_title_with_multiple_ufffd(self):
        item = _make_list_item(title="Hello wor��...", date="2026-03-01")
        existing = {"title": "Hello world peace", "date": "2026-03-01"}
        assert has_changed(item, existing) is False

    def test_real_title_change_still_detected(self):
        item = _make_list_item(title="Totally different title", date="2026-03-01")
        existing = {"title": "Original title", "date": "2026-03-01"}
        assert has_changed(item, existing) is True

    def test_empty_prefix_after_stripping_does_not_match_everything(self):
        # If everything before "..." is U+FFFD, we can't safely infer a match;
        # treat as changed rather than declaring a silent match on any old title.
        item = _make_list_item(title="�...", date="2026-03-01")
        existing = {"title": "Completely unrelated", "date": "2026-03-01"}
        assert has_changed(item, existing) is True


class TestUpsertNotice:
    async def test_set_excludes_edit_fields(self, mock_collection):
        mock_collection.update_one.return_value = MagicMock(upserted_id="new")
        notice = _make_notice()

        await upsert_notice(mock_collection, notice)

        call_args = mock_collection.update_one.call_args
        update_doc = call_args[0][1]

        # $set should NOT contain editHistory or editCount
        assert "editHistory" not in update_doc["$set"]
        assert "editCount" not in update_doc["$set"]

        # $setOnInsert should contain them
        assert "editHistory" in update_doc["$setOnInsert"]
        assert "editCount" in update_doc["$setOnInsert"]

    async def test_returns_inserted_when_upserted(self, mock_collection):
        mock_collection.update_one.return_value = MagicMock(upserted_id="new-id")
        result = await upsert_notice(mock_collection, _make_notice())
        assert result == "inserted"

    async def test_returns_updated_when_existing(self, mock_collection):
        mock_collection.update_one.return_value = MagicMock(upserted_id=None)
        result = await upsert_notice(mock_collection, _make_notice())
        assert result == "updated"


class TestUpdateWithHistory:
    async def test_push_edit_entry_with_slice(self, mock_collection):
        notice = _make_notice()
        edit_entry = {
            "detectedAt": datetime.now(timezone.utc),
            "oldHash": "old",
            "newHash": "new",
            "source": "tier1",
        }

        await update_with_history(mock_collection, notice, edit_entry)

        call_args = mock_collection.update_one.call_args
        update_doc = call_args[0][1]

        # $push with $each and $slice
        push = update_doc["$push"]["editHistory"]
        assert push["$each"] == [edit_entry]
        assert push["$slice"] == -20

        # $inc editCount
        assert update_doc["$inc"]["editCount"] == 1

    async def test_set_excludes_edit_fields(self, mock_collection):
        notice = _make_notice()
        edit_entry = {"source": "tier1"}

        await update_with_history(mock_collection, notice, edit_entry)

        update_doc = mock_collection.update_one.call_args[0][1]
        assert "editHistory" not in update_doc["$set"]
        assert "editCount" not in update_doc["$set"]

    async def test_no_upsert(self, mock_collection):
        """update_with_history는 기존 글 전용 — upsert=True가 아님."""
        notice = _make_notice()
        await update_with_history(mock_collection, notice, {"source": "tier1"})

        call_kwargs = mock_collection.update_one.call_args.kwargs
        assert call_kwargs.get("upsert", False) is False


class TestFindExistingMeta:
    async def test_projection_includes_content_hash(self, mock_collection):
        async def empty_cursor():
            return
            yield  # make it an async generator

        mock_collection.find = MagicMock(return_value=empty_cursor())

        await find_existing_meta(mock_collection, "dept-1", [1, 2])

        call_args = mock_collection.find.call_args
        projection = call_args[0][1]
        assert "contentHash" in projection
        assert projection["contentHash"] == 1

    async def test_returns_content_hash_in_result(self, mock_collection):
        async def cursor_with_doc():
            yield {"articleNo": 1, "title": "test", "date": "2026-03-01", "contentHash": "abc"}

        mock_collection.find = MagicMock(return_value=cursor_with_doc())

        result = await find_existing_meta(mock_collection, "dept-1", [1])
        assert result[1]["contentHash"] == "abc"

    async def test_content_hash_none_when_missing(self, mock_collection):
        async def cursor_with_doc():
            yield {"articleNo": 1, "title": "test", "date": "2026-03-01"}

        mock_collection.find = MagicMock(return_value=cursor_with_doc())

        result = await find_existing_meta(mock_collection, "dept-1", [1])
        assert result[1]["contentHash"] is None
