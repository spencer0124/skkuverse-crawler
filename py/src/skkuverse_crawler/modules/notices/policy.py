"""Pure crawl-policy predicates for SKKU list pages.

These are module-side, not plugin-side, on purpose: has_changed carries
the U+FFFD-truncation defence and should_continue/page_below_floor carry
the pinned-row incident fixes — putting them in a store plugin would make
them vanish from plugin-less runs and force every backend to reimplement
them (architecture ownership table). Bodies are byte-identical moves from
dedup.py / orchestrator.py (plan 위험 ③: 이동과 수정을 같은 커밋에 두지
않는다).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

from ...core.ports import SeenRecord
from .constants import (
    SERVICE_START_DATE,
    VIEWS_REFRESH_JITTER_HOURS,
    VIEWS_REFRESH_MIN_DELTA,
    VIEWS_REFRESH_MIN_INTERVAL_HOURS,
    VIEWS_REFRESH_MIN_RATIO,
)
from .models import NoticeListItem


def has_changed(item: NoticeListItem, previous: SeenRecord) -> bool:
    if item.date != previous.date:
        return True
    new_title = item.title
    old_title = previous.title
    if new_title == old_title:
        return False
    # Truncated list title (ends with "...") that matches the DB's full
    # title prefix is NOT a real change — the list page just shows a
    # shorter version than the detail-page title stored in the DB.
    # Some source servers truncate at a byte boundary inside a multi-byte
    # UTF-8 character, leaving one or more U+FFFD replacement chars before
    # "..."; strip those so the prefix match still succeeds.
    if new_title.endswith("..."):
        prefix = new_title[:-3].rstrip("�")
        if prefix and old_title.startswith(prefix):
            return False
    return True


def views_refresh_due(
    new_views: int | None,
    previous: SeenRecord,
    now: datetime | None = None,
) -> bool:
    """Whether an otherwise-unchanged notice is worth a write for its view
    counter alone.

    Gating only on "did it change" barely helps: a counter moves on most
    page-0 notices within any 30-minute tick, so ~809 of 1,455 touched
    documents would still write every time (prod, 2026-09-13). Two bounds
    turn that into an occasional write:

    - **at most once per VIEWS_REFRESH_MIN_INTERVAL_HOURS, plus a per-document
      offset.** The interval caps the cost — the whole page-0 set costs
      roughly (docs / interval) writes per tick instead of one each. The
      offset is what makes that a *rate* rather than a *rhythm*: without it
      every document that was written in the same tick also leaves the
      interval in the same tick, and the constant drip becomes a periodic
      spike of the same height. Peak is the axis the Atlas tier bills on, so
      a flat interval would have won only half the argument.
    - **unless the jump is large**, so a fast-moving notice is not pinned to
      a visibly wrong number for the whole interval. The app renders the
      count at full precision, so the staleness is real and worth bounding
      in relative terms.

    A previously-absent counter is always due: that write backfills it, and
    it happens once.
    """
    if new_views is None:
        return False
    old_views = previous.views
    if old_views is None:
        return True

    delta = abs(new_views - old_views)
    if delta == 0:
        return False
    if delta >= max(VIEWS_REFRESH_MIN_DELTA, old_views * VIEWS_REFRESH_MIN_RATIO):
        return True

    last_written = previous.crawled_at
    if last_written is None:
        return True
    # Stored datetimes may be naive (Mongo returns UTC without a tzinfo).
    # Comparing a naive to an aware datetime raises, and that exception would
    # surface as a per-item crawl error rather than anything legible.
    if last_written.tzinfo is None:
        last_written = last_written.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    # articleNo, not a random draw or a hash of the clock: the offset has to
    # be stable across restarts and re-crawls, or a document could shuffle
    # into an earlier slot on every pass and defeat the interval entirely.
    offset = previous.article_no % VIEWS_REFRESH_JITTER_HOURS
    due_after = timedelta(hours=VIEWS_REFRESH_MIN_INTERVAL_HOURS + offset)
    return reference - last_written >= due_after


def should_continue(
    page_items: list[NoticeListItem],
    existing_meta: Mapping[int, SeenRecord],
) -> bool:
    """True while the page still holds unknown regular rows.

    Pinned rows are excluded: they repeat on every page and, when they
    pre-date SERVICE_START_DATE, are never stored — counting them would keep
    every page looking "unknown" and defeat the all-known early-stop. Any
    pinned notice is always visible on page 0, so ignoring it here never
    skips content. A page with only pinned rows means regular posts ran out.
    """
    regular_items = [item for item in page_items if not item.pinned]
    return not all(item.articleNo in existing_meta for item in regular_items)


def page_below_floor(
    list_items: list[NoticeListItem],
    *,
    since: str | None = SERVICE_START_DATE,
) -> bool:
    """True when every regular row on the page pre-dates the floor date.

    Pinned rows repeat on every page, so a single recent pinned notice would
    otherwise keep this check false all the way to the last page. Judge the
    floor on regular rows only; a page with no regular rows falls through and
    stops via empty_list_page/all_known on the next one.

    since=None disables the floor entirely (OSS default once CrawlOptions
    moves to core); the notices module supplies SERVICE_START_DATE.
    """
    if since is None:
        return False
    regular_items = [item for item in list_items if not item.pinned]
    return bool(regular_items) and all(
        item.date and item.date < since for item in regular_items
    )
