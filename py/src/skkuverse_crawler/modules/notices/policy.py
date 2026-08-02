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

from ...core.ports import SeenRecord
from .constants import SERVICE_START_DATE
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
