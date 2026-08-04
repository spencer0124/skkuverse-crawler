"""HSSC campus shuttle: parse, normalise, and the sticky-timestamp state.

Port of skkuverse-server's `hssc.poller.service.ts`. The payload shape is
a contract with that server — it reads these documents by field name — so
the output keys are camelCase and match it exactly, including the ones
that look redundant.

Everything here is pure. `normalize` takes the previous observations and
the current instant as ARGUMENTS and returns the next state alongside the
items; it never reads `self`. That is what lets the parity tests replay a
month of captured responses deterministically, with no clock and no
network, and it is the only reason the sticky-timestamp behaviour is
testable at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping

from .time_ko import format_stamp, js_round, parse_korean, parse_stamp

# A bus is dropped once its last sighting is this old. The upstream never
# returns an empty array — it pins the last six rows indefinitely — so this
# filter, not the response, is what expresses "no buses are running".
STALE_DEFAULT = timedelta(minutes=10)
# The turnaround point gets a tighter window: a bus sits there between
# runs, so the default would keep reporting one long after it left.
STALE_TURNAROUND = timedelta(minutes=3)
TURNAROUND_STATION = "농구장 (셔틀버스정류소)"

# Upstream stop names are internal labels; these are what the app shows.
# Two upstream names collapse onto "정문" and two onto "600주년기념관" —
# the route passes each twice, outbound and inbound.
STOP_NAME_MAPPING: Mapping[str, str] = {
    "혜화역 1번출구 셔틀버스 정류소": "혜화역 1번출구 (셔틀버스정류소)",
    "혜화동로터리": "혜화동로터리 [미정차]",
    "성균관대입구사거리": "성균관대입구사거리",
    "문묘입구[정문]-등교": "정문",
    "600주년기념관 앞-등교": "600주년기념관",
    "농구장정류소": "농구장 (셔틀버스정류소)",
    "문묘입구[정문]-하교": "정문",
    "올림픽기념국민생활관": "올림픽기념국민생활관 [하차전용]",
    "600주년기념관 앞-하교": "600주년기념관",
    "서울혜화동우체국": "혜화동우체국 [하차전용]",
}


# [0-9], not \d: Python's \d is Unicode-aware and matches Arabic-Indic
# digits, which int() then happily parses into a number the upstream never
# sent. Surrounding whitespace is tolerated because parseInt tolerates it
# and the corpus contains padded values.
_INTEGER = re.compile(r"^\s*[+-]?[0-9]+\s*$")


@dataclass(frozen=True)
class HsscRow:
    """One upstream row, unchanged. Parsing only checks shape."""

    line_no: str
    inout: str
    stop_no: str
    seq: str
    stop_name: str
    get_date: str


class HsscPayloadError(ValueError):
    """The upstream response was not the shape this parser accepts."""


def parse(data: Any) -> list[HsscRow] | None:
    """Raw response -> rows, or None when there is nothing to act on.

    None and `[]` are different answers and the caller must keep them
    apart: a non-array response means the upstream misbehaved and the
    stored document should be left alone, while an empty array is a real
    statement that no buses are running.
    """
    if not isinstance(data, list):
        return None
    rows = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise HsscPayloadError(f"item[{i}] is {type(item).__name__}, expected object")
        try:
            rows.append(
                HsscRow(
                    line_no=str(item["line_no"]),
                    inout=str(item["inout"]),
                    stop_no=str(item["stop_no"]),
                    seq=str(item["seq"]),
                    stop_name=str(item["stop_name"]),
                    get_date=str(item["get_date"]),
                )
            )
        except KeyError as exc:
            raise HsscPayloadError(f"item[{i}] is missing {exc.args[0]!r}") from exc
        # `seq` becomes an integer downstream. The TypeScript's parseInt
        # degrades to NaN and publishes the literal string "NaN" as the
        # station sequence; refusing is better, but it has to happen HERE,
        # where the error names the offending item and carries this
        # module's own type — from inside normalize() it escaped as a bare
        # ValueError and took the whole tick with it.
        if not _INTEGER.match(rows[-1].seq):
            raise HsscPayloadError(
                f"item[{i}].seq is {rows[-1].seq!r}, expected an integer"
            )
    return rows


def linear_sequence(seq: int) -> int:
    """Upstream `seq` is a circular index 0-10; the app wants 1-11.

    The route's numbering starts mid-circle, so the halves are rotated
    rather than shifted: 5..10 become 1..6 and 0..4 become 7..11.
    """
    return seq - 4 if seq >= 5 else seq + 7


def normalize(
    previous: list[dict[str, Any]],
    rows: list[HsscRow],
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    """Rows -> the payload stored under the `hssc` cache key.

    `previous` is the last payload this function returned, and it carries
    the state: when a bus is seen again at the same stop, the FIRST
    sighting's timestamp is reused so `estimatedTime` accumulates into a
    dwell time instead of resetting to zero every tick. Without that the
    app could never show "has been here 4 minutes".

    Note `previous` is the post-filter list, so a bus that ages out loses
    its sticky timestamp and starts fresh if it reappears. That is the
    upstream behaviour, not an oversight.
    """
    # FIRST match wins, matching the TypeScript's `Array.find`. A dict
    # comprehension would let a later duplicate overwrite an earlier one,
    # and two buses of one line at one stop is a real (if rare) state —
    # the difference there is the whole dwell time, not a rounding.
    sticky: dict[tuple[str, str], str] = {}
    for item in previous:
        sticky.setdefault((item["line_no"], item["stop_no"]), item["eventDate"])

    normalised: list[dict[str, Any]] = []
    for row in rows:
        carried = sticky.get((row.line_no, row.stop_no))
        event_at = parse_stamp(carried) if carried else parse_korean(row.get_date)
        normalised.append(
            {
                # Upstream fields, passed through — the server's response
                # DTO still exposes some of them.
                "line_no": row.line_no,
                "inout": row.inout,
                "stop_no": row.stop_no,
                "seq": row.seq,
                "stop_name": row.stop_name,
                "get_date": row.get_date,
                # Derived.
                "sequence": str(linear_sequence(int(row.seq))),
                "stationName": STOP_NAME_MAPPING.get(row.stop_name, row.stop_name),
                # The upstream does not report plate numbers for the
                # shuttle; the app's card expects the field regardless.
                "carNumber": "0000",
                "eventDate": format_stamp(event_at),
                "estimatedTime": js_round(abs((now - event_at).total_seconds())),
                "isLastBus": False,
            }
        )

    return [item for item in normalised if not _is_stale(item, now=now)]


def _is_stale(item: dict[str, Any], *, now: datetime) -> bool:
    window = (
        STALE_TURNAROUND if item["stationName"] == TURNAROUND_STATION else STALE_DEFAULT
    )
    return parse_stamp(item["eventDate"]) < now - window
