from __future__ import annotations

from skkuverse_crawler.core.ports import SeenRecord
from skkuverse_crawler.modules.notices.models import NoticeListItem
from skkuverse_crawler.modules.notices.policy import (
    has_changed,
    page_below_floor,
    should_continue,
)


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
        existing = SeenRecord(article_no=1, title="Hello", date="2026-03-01")
        assert has_changed(item, existing) is False

    def test_date_differs_is_changed(self):
        item = _make_list_item(title="Hello", date="2026-03-02")
        existing = SeenRecord(article_no=1, title="Hello", date="2026-03-01")
        assert has_changed(item, existing) is True

    def test_truncated_title_with_ellipsis_matches_prefix(self):
        item = _make_list_item(title="Very long announcemen...", date="2026-03-01")
        existing = SeenRecord(article_no=1, title="Very long announcement about stuff", date="2026-03-01")
        assert has_changed(item, existing) is False

    def test_truncated_title_with_ufffd_before_ellipsis(self):
        # cal.skku.edu style: source byte-truncates title mid multi-byte
        # character, resulting in a trailing U+FFFD before "...".
        item = _make_list_item(
            title="[IBK기업은행] 2026년 전문·일반계약직 및 전문준정규직 채용�...",
            date="2026-04-20",
        )
        existing = SeenRecord(
            article_no=1, title="[IBK기업은행] 2026년 전문·일반계약직 및 전문준정규직 채용공고 (~5/4, 10:00)", date="2026-04-20",
        )
        assert has_changed(item, existing) is False

    def test_truncated_title_with_multiple_ufffd(self):
        item = _make_list_item(title="Hello wor��...", date="2026-03-01")
        existing = SeenRecord(article_no=1, title="Hello world peace", date="2026-03-01")
        assert has_changed(item, existing) is False

    def test_real_title_change_still_detected(self):
        item = _make_list_item(title="Totally different title", date="2026-03-01")
        existing = SeenRecord(article_no=1, title="Original title", date="2026-03-01")
        assert has_changed(item, existing) is True

    def test_empty_prefix_after_stripping_does_not_match_everything(self):
        # If everything before "..." is U+FFFD, we can't safely infer a match;
        # treat as changed rather than declaring a silent match on any old title.
        item = _make_list_item(title="�...", date="2026-03-01")
        existing = SeenRecord(article_no=1, title="Completely unrelated", date="2026-03-01")
        assert has_changed(item, existing) is True


class TestShouldContinue:
    """all-known early-stop 판정 — 고정글(pinned)은 제외."""

    def _item(self, article_no: int, pinned: bool = False) -> NoticeListItem:
        item = NoticeListItem(
            articleNo=article_no, title="제목", category="", author="a",
            date="2026-04-15", views=1, detailPath=f"?articleNo={article_no}",
        )
        item.pinned = pinned
        return item

    def test_unknown_regular_continues(self):
        assert should_continue([self._item(1)], {}) is True

    def test_all_regulars_known_stops(self):
        meta = {1: SeenRecord(article_no=1, title="제목", date="2026-04-15")}
        assert should_continue([self._item(1)], meta) is False

    def test_unknown_old_pinned_does_not_block_stop(self):
        """floor 이전 고정글은 DB에 없어도 all-known stop을 막지 않음."""
        meta = {1: SeenRecord(article_no=1, title="제목", date="2026-04-15")}
        items = [self._item(99, pinned=True), self._item(1)]
        assert should_continue(items, meta) is False

    def test_pinned_only_page_stops(self):
        """고정글만 남은 페이지 = 일반 글 소진 → stop."""
        assert should_continue([self._item(99, pinned=True)], {}) is False


class TestPageBelowFloor:
    """page_below_floor: 고정글(pinned)은 floor 판정에서 제외."""

    def test_all_regular_old_stops(self):
        items = [_make_list_item(articleNo=n, date="2025-12-01") for n in (1, 2)]
        assert page_below_floor(items) is True

    def test_recent_pinned_does_not_block_stop(self):
        """최신 고정글이 반복 노출되어도 일반 글이 전부 오래됐으면 stop."""
        pinned = _make_list_item(articleNo=99, date="2026-05-01")
        pinned.pinned = True
        regulars = [_make_list_item(articleNo=n, date="2025-12-01") for n in (1, 2)]
        assert page_below_floor([pinned, *regulars]) is True

    def test_recent_regular_continues(self):
        items = [
            _make_list_item(articleNo=1, date="2025-12-01"),
            _make_list_item(articleNo=2, date="2026-04-15"),
        ]
        assert page_below_floor(items) is False

    def test_pinned_only_page_continues(self):
        """고정글만 있는 페이지는 stop 안 함 — 다음 페이지의 empty/all_known이 처리."""
        pinned = _make_list_item(articleNo=99, date="2022-03-16")
        pinned.pinned = True
        assert page_below_floor([pinned]) is False

    def test_missing_date_continues(self):
        items = [_make_list_item(articleNo=1, date="")]
        assert page_below_floor(items) is False
