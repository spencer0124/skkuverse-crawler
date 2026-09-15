from __future__ import annotations

from datetime import datetime, timedelta, timezone

from skkuverse_crawler.core.ports import SeenRecord
from skkuverse_crawler.modules.notices.models import NoticeListItem
from skkuverse_crawler.modules.notices.constants import (
    VIEWS_REFRESH_JITTER_TICKS,
    VIEWS_REFRESH_TICK_MINUTES,
)
from skkuverse_crawler.modules.notices.policy import (
    has_changed,
    page_below_floor,
    should_continue,
    views_refresh_due,
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

    def test_since_none_disables_floor(self):
        items = [_make_list_item(articleNo=1, date="2000-01-01")]
        assert page_below_floor(items, since=None) is False

    def test_custom_since_respected(self):
        items = [_make_list_item(articleNo=1, date="2026-04-01")]
        assert page_below_floor(items, since="2026-05-01") is True
        assert page_below_floor(items, since="2026-03-01") is False


NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def _seen(
    views: int | None,
    *,
    written_hours_ago: float | None = 0.0,
    article_no: int = 8,  # 8 % JITTER_TICKS == 0, so the plain interval applies
) -> SeenRecord:
    return SeenRecord(
        article_no=article_no,
        title="t",
        date="2026-09-13",
        views=views,
        crawled_at=(
            None if written_hours_ago is None
            else NOW - timedelta(hours=written_hours_ago)
        ),
    )


class TestViewsRefreshDue:
    """adr-009 — when an otherwise-unchanged notice earns a write.

    Gating on "did the counter change" alone was measured to leave ~56% of
    the per-tick writes in place, because counters move on most page-0 rows
    within 30 minutes. The rate limit is what actually cuts the cost; the
    magnitude escape is what keeps a busy notice from showing a visibly
    wrong number for the whole interval.
    """

    def test_unchanged_counter_never_writes(self):
        assert views_refresh_due(500, _seen(500), NOW) is False

    def test_unchanged_counter_never_writes_even_when_long_stale(self):
        # The rate limit opens a window; it does not manufacture a reason.
        assert views_refresh_due(500, _seen(500, written_hours_ago=999), NOW) is False

    def test_small_move_inside_the_interval_is_skipped(self):
        # This is the case that pays for the change: a busy notice ticking
        # over between crawls used to cost a write every 30 minutes.
        assert views_refresh_due(505, _seen(500, written_hours_ago=0.5), NOW) is False

    def test_small_move_writes_once_the_interval_has_passed(self):
        # article_no 8 -> offset 0 ticks, so the bare interval applies.
        assert views_refresh_due(505, _seen(500, written_hours_ago=6), NOW) is True

    def test_large_absolute_jump_writes_immediately(self):
        # A fresh notice is inserted with a single-digit count; 10% of that
        # is meaningless, so the absolute floor is what rescues it.
        assert views_refresh_due(60, _seen(5, written_hours_ago=0.5), NOW) is True

    def test_large_relative_jump_writes_immediately(self):
        # 10% of 10,000 is 1,000, which clears the absolute floor of 50 —
        # so the ratio, not the floor, is the binding constraint up here.
        assert views_refresh_due(11_200, _seen(10_000, written_hours_ago=0.5), NOW) is True

    def test_ratio_binds_above_the_floor(self):
        # +200 on 10,000 beats the absolute floor but is under 10%, so it
        # waits for the interval rather than writing.
        assert views_refresh_due(10_200, _seen(10_000, written_hours_ago=0.5), NOW) is False

    def test_absent_stored_counter_always_writes(self):
        # Backfills a document written before `views` existed. Happens once.
        assert views_refresh_due(7, _seen(None, written_hours_ago=0.0), NOW) is True

    def test_absent_scraped_counter_writes_nothing(self):
        # A source that does not publish counts must not thrash the field.
        assert views_refresh_due(None, _seen(500), NOW) is False

    def test_unknown_last_write_is_treated_as_due(self):
        assert views_refresh_due(501, _seen(500, written_hours_ago=None), NOW) is True

    def test_naive_stored_datetime_does_not_raise(self):
        # Mongo hands back UTC without a tzinfo. Subtracting a naive from an
        # aware datetime raises TypeError, and the runner would count that as
        # a per-item crawl error rather than surfacing anything legible.
        naive = SeenRecord(
            article_no=1, title="t", date="2026-09-13", views=500,
            crawled_at=datetime(2026, 9, 13, 0, 0),  # no tzinfo
        )
        assert views_refresh_due(501, naive, NOW) is True

    def test_counter_going_backwards_is_a_real_move(self):
        # Boards do reset or correct counts; |delta| keeps that a write
        # rather than something that silently never reconciles.
        assert views_refresh_due(10, _seen(5_000, written_hours_ago=0.5), NOW) is True


class TestViewsRefreshJitter:
    """adr-009 amendment — the interval must be a rate, not a rhythm.

    Observed on the first tick after deploy: 1 write, because the last
    pre-deploy tick had written every page-0 document inside the same two
    minutes, so all of them were still inside the interval. They would have
    *left* it inside the same two minutes as well, six hours later — the
    constant drip becoming a periodic spike of the same height. Peak ops/s
    is the axis the Atlas tier bills on, so that would have won only half
    the argument.
    """

    def test_offset_delays_a_document_past_the_bare_interval(self):
        # article_no 1 -> offset 1 tick (30 min), so 6h is not yet due for it
        # even though it is due for one whose offset is 0.
        at_six = dict(views=500, written_hours_ago=6)
        assert views_refresh_due(505, _seen(**at_six, article_no=8), NOW) is True
        assert views_refresh_due(505, _seen(**at_six, article_no=1), NOW) is False

    def test_offset_document_becomes_due_at_its_own_slot(self):
        assert views_refresh_due(505, _seen(500, written_hours_ago=6.5, article_no=1), NOW) is True

    def test_offset_is_quantised_to_the_tick_not_the_hour(self):
        """A write can only land on a tick, so an offset coarser than the
        tick period just makes fewer, bigger lumps. article_no 1 must come
        due half an hour after the bare interval, not a full hour."""
        assert views_refresh_due(505, _seen(500, written_hours_ago=6.4, article_no=1), NOW) is False
        assert views_refresh_due(505, _seen(500, written_hours_ago=6.5, article_no=1), NOW) is True

    def test_documents_written_together_spread_across_every_tick(self):
        """The property that matters: a cohort written in one tick must not
        leave the interval in one tick — and must spread across TICKS, not
        just hours. At hourly granularity this cohort released into 4 slots
        and left the other 8 in its window empty."""
        cohort = range(400)
        # Tick-by-tick from the bare interval to interval + max offset.
        slots = [6.0 + t * 0.5 for t in range(VIEWS_REFRESH_JITTER_TICKS)]
        cumulative = [
            sum(
                1
                for a in cohort
                if views_refresh_due(505, _seen(500, written_hours_ago=h, article_no=a), NOW)
            )
            for h in slots
        ]
        released = [cumulative[0]] + [
            cumulative[i] - cumulative[i - 1] for i in range(1, len(cumulative))
        ]

        assert cumulative == sorted(cumulative)
        assert cumulative[-1] == len(cohort), "all released by interval + max offset"
        # Every tick in the window carries part of the cohort — none is idle,
        # which is exactly what the hourly version got wrong.
        assert all(r > 0 for r in released), released
        # ...and none carries a disproportionate share.
        assert max(released) <= 2 * (len(cohort) // VIEWS_REFRESH_JITTER_TICKS), released

    def test_offset_is_stable_for_a_given_document(self):
        # Derived from articleNo, not from the clock or a random draw — a
        # document that reshuffled each pass could land in an earlier slot
        # every time and never actually wait out the interval.
        a = _seen(500, written_hours_ago=6.5, article_no=7)
        assert [views_refresh_due(505, a, NOW) for _ in range(5)] == [
            views_refresh_due(505, a, NOW)
        ] * 5

    def test_max_staleness_envelope_is_unchanged_from_the_hourly_version(self):
        # 8 ticks x 30 min == the 4 hours the hourly offset spanned, so this
        # refinement buys smoothness without widening the staleness bound.
        assert VIEWS_REFRESH_JITTER_TICKS * VIEWS_REFRESH_TICK_MINUTES == 4 * 60

    def test_jitter_never_shortens_the_interval(self):
        # The offset is additive only. A document must never become due
        # earlier than VIEWS_REFRESH_MIN_INTERVAL_HOURS.
        for a in range(50):
            assert (
                views_refresh_due(505, _seen(500, written_hours_ago=5.9, article_no=a), NOW)
                is False
            )
