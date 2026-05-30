from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ScheduleEvent:
    """A single academic-calendar entry.

    ``month`` is the SKKU academic-year month group the source files the event
    under (3-12, plus 1-2 which spill into the *next* calendar year). It is NOT
    necessarily ``startDate``'s calendar month near the 학년도 boundary.
    ``endDate`` is ``None`` when the source provides no end date (single-day
    event / empty ``ed_*`` field).
    """

    month: int
    startDate: str  # YYYY-MM-DD
    endDate: str | None  # YYYY-MM-DD or None
    content: str
