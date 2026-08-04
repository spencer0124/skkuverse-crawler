"""Korean-locale timestamps, without a locale and without tzdata.

The HSSC upstream stamps its rows `"2026-03-16 오전 8:58:46"`. The
TypeScript poller parsed that with `moment.tz(..., "YYYY-MM-DD a h:mm:ss",
"ko", "Asia/Seoul")`. Neither half of that translates safely:

- **Not ``strptime`` with ``%p``.** ``%p`` is locale-dependent. Replacing
  오전/오후 with AM/PM and hoping the container's ``LC_TIME`` is C works
  until it isn't, and the failure is a ``ValueError`` three frames up
  rather than something that names the format.
- **Not ``zoneinfo``.** ``python:3.12-slim`` does not reliably ship
  ``/usr/share/zoneinfo``; ``ZoneInfo("Asia/Seoul")`` would raise at the
  first tick. ``docker-compose.yml`` sets ``TZ=Asia/Seoul``, which
  *suggests* tzdata is installed — but that is an inference, and this
  repo's packaging tests exist because ``lxml`` taught us what inference
  costs. Korea has had no DST since 1988, so a fixed offset is exact.
  ``plugins/health/logic.py`` already does this.

So: a regex, and arithmetic. That removes the locale, ``%p`` and ``%I``
entirely, and turns "upstream changed its format" into a loud failure
naming the string instead of a swallowed parse error.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone

# Korea has had no daylight saving since 1988; KST is a fixed +09:00.
KST = timezone(timedelta(hours=9))

# "2026-03-16 오전 8:58:46" — hour is 1..12 and may be unpadded.
_KOREAN_MERIDIEM = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})\s+(오전|오후)\s+(\d{1,2}):(\d{2}):(\d{2})$"
)

# "2026-03-16 08:58:46" — what this module re-emits, and therefore what it
# has to be able to read back when a stored value is reused.
_ISO_LIKE = re.compile(r"^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$")

FORMAT = "%Y-%m-%d %H:%M:%S"


class KoreanTimeFormatError(ValueError):
    """An upstream timestamp did not match either accepted shape."""


def parse_korean(value: str) -> datetime:
    """Parse `"YYYY-MM-DD 오전|오후 h:mm:ss"` as an aware KST datetime.

    The 12-hour boundary is the part worth stating: 오전 12시 is midnight
    (hour 0) and 오후 12시 is noon (hour 12). Every other 오후 hour is
    +12. Getting this backwards shifts two hours a day by twelve hours,
    which looks like plausible data.
    """
    match = _KOREAN_MERIDIEM.match(value.strip())
    if match is None:
        raise KoreanTimeFormatError(
            f"expected 'YYYY-MM-DD 오전|오후 h:mm:ss', got {value!r}"
        )
    year, month, day, meridiem, hour, minute, second = match.groups()
    hour12 = int(hour)
    if not 1 <= hour12 <= 12:
        raise KoreanTimeFormatError(f"hour out of range for a 12-hour clock: {value!r}")
    if meridiem == "오전":
        hour24 = 0 if hour12 == 12 else hour12
    else:
        hour24 = 12 if hour12 == 12 else hour12 + 12
    return _build(value, int(year), int(month), int(day), hour24, int(minute), int(second))


def parse_stamp(value: str) -> datetime:
    """Read back a timestamp this module previously emitted.

    Separate from `parse_korean` on purpose: the sticky-timestamp path
    reuses a value it wrote itself, and accepting either shape in one
    function would let a raw upstream string flow into a slot that is
    supposed to hold a normalised one.
    """
    match = _ISO_LIKE.match(value.strip())
    if match is None:
        raise KoreanTimeFormatError(f"expected 'YYYY-MM-DD HH:MM:SS', got {value!r}")
    year, month, day, hour, minute, second = match.groups()
    return _build(
        value, int(year), int(month), int(day), int(hour), int(minute), int(second)
    )


def _build(
    original: str,
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
) -> datetime:
    """Construct, translating the calendar check into this module's error.

    The regexes validate shape only — "2026-02-30" and "8:99:99" match
    them fine. `datetime()` catches those, but as a bare ValueError whose
    message ("day is out of range for month") names neither the field nor
    the input. A caller following the documented contract
    (`except KoreanTimeFormatError`) would miss it entirely.
    """
    try:
        return datetime(year, month, day, hour, minute, second, tzinfo=KST)
    except ValueError as exc:
        raise KoreanTimeFormatError(f"{original!r} is not a real instant: {exc}") from exc


def format_stamp(moment: datetime) -> str:
    """`"YYYY-MM-DD HH:MM:SS"` in KST — the shape stored in `eventDate`.

    Naive input is treated as already-KST rather than as UTC: everything
    this module handles is Korean local time, and silently shifting by
    nine hours is worse than being explicit.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=KST)
    return moment.astimezone(KST).strftime(FORMAT)


# ── matching JavaScript, where the reference implementation lives ─────────


def js_round(value: float) -> int:
    """`Math.round`, which is not Python's `round`.

    JavaScript rounds a half away from zero; Python rounds it to even, so
    `round(40.5)` is 40 where `Math.round(40.5)` is 41. Every fixture
    timestamp is whole-second, so the goldens cannot see this — but in
    production `now` carries sub-second precision against a second-precision
    event, and an exact .5 lands whenever the tick's millisecond is 500.
    """
    return math.floor(value + 0.5)


def js_iso(moment: datetime) -> str:
    """`Date.prototype.toISOString()`, exactly.

    The stored `recordTime`/`eventDate` strings are a contract with
    skkuverse-server, and JavaScript always emits three-digit milliseconds
    and a literal Z. Python's `isoformat()` omits the fractional part when
    it is zero — which is every timestamp here — so the naive version
    produces `...:11Z` where the server wrote `...:11.000Z`. Same instant,
    different string, and the app compares strings.
    """
    utc = moment.astimezone(timezone.utc)
    return f"{utc.strftime('%Y-%m-%dT%H:%M:%S')}.{utc.microsecond // 1000:03d}Z"
