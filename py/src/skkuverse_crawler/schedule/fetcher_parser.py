from __future__ import annotations

import hashlib
import json
import re

from ..notices.parser import load_html
from ..shared.logger import get_logger
from .models import ScheduleEvent

logger = get_logger("schedule.parser")

BASE_URL = "https://www.skku.edu/skku/edu/bachelor/ca_de_schedule.do"

_YEAR_PARAM_RE = re.compile(r"srBachelorYear=(\d+)")


def year_url(year: int) -> str:
    return f"{BASE_URL}?mode=view&srBachelorYear={year}"


def parse_available_years(html: str) -> list[int]:
    """Authoritative list of published academic years.

    Read ONLY from the base (no-param) page's ``<select id="tab_select">``.
    On a year-specific request the site echoes the *requested* year into this
    dropdown even when it is not actually published, so the dropdown of a
    specific-year page is not trustworthy. Returns sorted unique years.
    """
    soup = load_html(html)
    select = soup.select_one("select#tab_select")
    if select is None:
        return []
    years: set[int] = set()
    for option in select.select("option"):
        value = option.get("value") or ""
        m = _YEAR_PARAM_RE.search(str(value))
        if m:
            years.add(int(m.group(1)))
    return sorted(years)


def parse_served_year(html: str) -> int | None:
    """The academic year the page actually SERVED (not what was requested).

    Primary signal: hidden ``<input name="bachelor_year" value="...">``.
    Fallback: the ``selected`` option in ``<select id="tab_select">``.
    Comparing this against the requested year detects the site's silent
    fallback (unpublished year -> current year's data, HTTP 200).
    """
    soup = load_html(html)
    inp = soup.select_one('input[name="bachelor_year"]')
    if inp is not None:
        value = inp.get("value")
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())

    selected = soup.select_one("select#tab_select option[selected]")
    if selected is not None:
        m = _YEAR_PARAM_RE.search(str(selected.get("value") or ""))
        if m:
            return int(m.group(1))
    return None


def parse_events(html: str) -> list[ScheduleEvent]:
    """Parse the embedded schedule JSON into ScheduleEvent records.

    The data lives in ``<textarea name="articleText">`` as JSON whose top-level
    keys are ``bachelor_<month>``; each maps to a 1-element array holding one
    object with flattened keys ``sd_<month>_<i>`` / ``ed_<month>_<i>`` /
    ``con_<month>_<i>`` plus ``size``. We trust the present keys rather than
    ``size`` (and warn on mismatch) to tolerate off-by-one source quirks.
    """
    soup = load_html(html)
    textarea = soup.select_one('textarea[name="articleText"]')
    if textarea is None:
        raise ValueError("articleText textarea not found")

    # textarea is RCDATA: BeautifulSoup already decodes HTML entities (&#034; -> ")
    data = json.loads(textarea.get_text())

    events: list[ScheduleEvent] = []
    for key, value in data.items():
        m = re.fullmatch(r"bachelor_(\d+)", key)
        if not m or not isinstance(value, list) or not value:
            continue
        month = int(m.group(1))
        obj = value[0]
        if not isinstance(obj, dict):
            continue

        idx_re = re.compile(rf"sd_{month}_(\d+)")
        indices = sorted(
            {int(mm.group(1)) for k in obj if (mm := idx_re.fullmatch(k))}
        )
        size = obj.get("size")
        if isinstance(size, int) and size != len(indices):
            logger.warning(
                "size_key_mismatch", month=month, size=size, found=len(indices)
            )

        for i in indices:
            sd = (obj.get(f"sd_{month}_{i}") or "").strip()
            ed = (obj.get(f"ed_{month}_{i}") or "").strip()
            con = (obj.get(f"con_{month}_{i}") or "").strip()
            if not sd:
                continue
            events.append(
                ScheduleEvent(
                    month=month,
                    startDate=sd,
                    endDate=ed or None,
                    content=con,
                )
            )
    return events


def compute_year_hash(events: list[ScheduleEvent]) -> str:
    """Order-independent SHA256 of a year's events for change detection.

    Canonicalize by sorting on (startDate, endDate, content) so the source's
    month grouping / key ordering never produces a false "changed".
    """
    canonical = sorted(
        (
            {
                "month": e.month,
                "startDate": e.startDate,
                "endDate": e.endDate or "",
                "content": e.content,
            }
            for e in events
        ),
        key=lambda d: (d["startDate"], d["endDate"], d["content"]),
    )
    blob = json.dumps(canonical, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
