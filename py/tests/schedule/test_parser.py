from __future__ import annotations

import json

from skkuverse_crawler.schedule import fetcher_parser as fp
from skkuverse_crawler.schedule.models import ScheduleEvent


def build_page(
    *,
    served_year: int = 2026,
    dropdown_years: tuple[int, ...] = (2024, 2025, 2026),
    schedule_obj: dict | None = None,
    include_input: bool = True,
    entity_encode: bool = False,
) -> str:
    options = "".join(
        f'<option {"selected=selected " if y == served_year else ""}'
        f'value="?mode=view&srBachelorYear={y}">{y}</option>'
        for y in dropdown_years
    )
    body = json.dumps(schedule_obj if schedule_obj is not None else {}, ensure_ascii=False)
    if entity_encode:
        body = body.replace('"', "&#034;")
    input_html = (
        f'<input name="bachelor_year" value="{served_year}"/>' if include_input else ""
    )
    return (
        "<html><body>"
        f"{input_html}"
        f'<select id="tab_select">{options}</select>'
        f'<textarea style="display:none" name="articleText">{body}</textarea>'
        "</body></html>"
    )


AUG = {
    "bachelor_8": [
        {
            "sd_8_0": "2026-08-10",
            "ed_8_0": "2026-08-12",
            "con_8_0": "2026학년도 2학기 등록금 분할납부 신청",
            "sd_8_1": "2026-08-25",
            "ed_8_1": "",
            "con_8_1": "2026년 여름 학위수여식",
            "size": 2,
        }
    ]
}


def test_year_url():
    assert fp.year_url(2026) == (
        "https://www.skku.edu/skku/edu/bachelor/ca_de_schedule.do"
        "?mode=view&srBachelorYear=2026"
    )


def test_parse_available_years():
    html = build_page(dropdown_years=(2024, 2025, 2026))
    assert fp.parse_available_years(html) == [2024, 2025, 2026]


def test_parse_available_years_empty_when_no_select():
    assert fp.parse_available_years("<html><body>no select</body></html>") == []


def test_parse_served_year_from_input():
    html = build_page(served_year=2026)
    assert fp.parse_served_year(html) == 2026


def test_parse_served_year_fallback_to_selected_option():
    # No hidden input -> fall back to the selected dropdown option.
    html = build_page(served_year=2025, include_input=False)
    assert fp.parse_served_year(html) == 2025


def test_parse_served_year_none_when_absent():
    assert fp.parse_served_year("<html><body></body></html>") is None


def test_parse_events_flattens_months():
    events = fp.parse_events(build_page(schedule_obj=AUG))
    assert len(events) == 2
    assert events[0] == ScheduleEvent(
        month=8,
        startDate="2026-08-10",
        endDate="2026-08-12",
        content="2026학년도 2학기 등록금 분할납부 신청",
    )


def test_empty_end_date_becomes_null():
    events = fp.parse_events(build_page(schedule_obj=AUG))
    august_25 = next(e for e in events if e.startDate == "2026-08-25")
    assert august_25.endDate is None


def test_absent_months_are_skipped():
    # Only bachelor_8 present (no 1/2, no 3..7) -> parses without crashing.
    events = fp.parse_events(build_page(schedule_obj=AUG))
    assert {e.month for e in events} == {8}


def test_size_key_mismatch_tolerated():
    obj = {
        "bachelor_9": [
            {
                "sd_9_0": "2026-09-01",
                "ed_9_0": "",
                "con_9_0": "개강",
                "size": 5,  # lies: only one event actually present
            }
        ]
    }
    events = fp.parse_events(build_page(schedule_obj=obj))
    assert len(events) == 1


def test_event_with_empty_start_date_skipped():
    obj = {
        "bachelor_9": [
            {
                "sd_9_0": "",
                "ed_9_0": "",
                "con_9_0": "no date",
                "sd_9_1": "2026-09-02",
                "ed_9_1": "",
                "con_9_1": "real",
                "size": 2,
            }
        ]
    }
    events = fp.parse_events(build_page(schedule_obj=obj))
    assert len(events) == 1
    assert events[0].content == "real"


def test_html_entities_unescaped():
    # Real page encodes JSON quotes as &#034;; BeautifulSoup must decode them.
    html = build_page(schedule_obj=AUG, entity_encode=True)
    events = fp.parse_events(html)
    assert len(events) == 2


def test_missing_textarea_raises():
    import pytest

    with pytest.raises(ValueError):
        fp.parse_events("<html><body>no textarea</body></html>")


def test_year_hash_is_order_independent():
    a = [
        ScheduleEvent(8, "2026-08-10", "2026-08-12", "A"),
        ScheduleEvent(8, "2026-08-25", None, "B"),
    ]
    b = list(reversed(a))
    assert fp.compute_year_hash(a) == fp.compute_year_hash(b)


def test_year_hash_changes_on_content_edit():
    a = [ScheduleEvent(8, "2026-08-10", "2026-08-12", "A")]
    b = [ScheduleEvent(8, "2026-08-10", "2026-08-12", "A (정정)")]
    assert fp.compute_year_hash(a) != fp.compute_year_hash(b)
