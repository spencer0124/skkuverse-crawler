"""Campus-to-campus driving ETA: the Naver Directions envelope and the
Korean duration string.

Port of skkuverse-server's `campus-eta/campus-eta.service.ts`. Pure, like
`hssc` and `jongro`: no clock, no network, no `self`.

Unlike those two this one has **no parity corpus**. The server never
polled it — `CampusEtaService` computes on demand into a ten-minute
in-memory cache — so there are no captured upstream responses to replay
and no transform output to diff against. The evidence for this port is
hand-written tests read against the TypeScript, which is weaker than a
month of goldens, and worth saying out loud rather than letting the
directory's other files imply otherwise.

The stale-cache behaviour does not move with the code. The TypeScript
keeps the last good `EtaData` in memory and returns it when both
directions fail; here the *stored document* is that cache, so a failing
tick simply writes nothing and the previous document stands. That is the
same behaviour with one fewer copy of the state — and `fetchedAt` is what
tells a reader how old the answer is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from .time_ko import js_round

# lng,lat — the order Naver Directions takes, which is the reverse of the
# lat,lng most map APIs use. Swapping them does not error; it routes
# between two points in the Yellow Sea.
SEOUL_CAMPUS = "126.993688,37.587308"
SUWON_CAMPUS = "126.975532,37.292345"

NAVER_DIRECTIONS_URL = (
    "https://naveropenapi.apigw.ntruss.com/map-direction/v1/driving"
)

# Header names for the two credentials. Passed as arguments from wiring —
# `modules/` may not read the environment — and never logged.
KEY_ID_HEADER = "X-NCP-APIGW-API-KEY-ID"
KEY_HEADER = "X-NCP-APIGW-API-KEY"

# campus-eta.service.ts uses `timeout: 5000` where the two realtime pollers
# use 10000. Half the patience, stated here rather than inherited from the
# client's default, which is the other upstreams' number.
TIMEOUT_SECONDS = 5.0

#: (payload field, (start, goal)) — 인사캠→자연캠 and back. Both the
#: scheduled module and `bus --once` walk this table, so the two cannot
#: end up asking for different directions or naming them differently.
LEGS: tuple[tuple[str, tuple[str, str]], ...] = (
    ("inja", (SEOUL_CAMPUS, SUWON_CAMPUS)),
    ("jain", (SUWON_CAMPUS, SEOUL_CAMPUS)),
)


class CampusEtaPayloadError(ValueError):
    """The Naver response was not the shape this parser accepts.

    Raised here, where the message can name the field, rather than letting
    a missing key escape as a bare TypeError from inside the tick.
    """


@dataclass(frozen=True)
class EtaLeg:
    """One direction. `duration` is milliseconds, as Naver reports it."""

    duration: int
    duration_text: str
    distance: int

    def as_fields(self) -> dict[str, Any]:
        """camelCase, because these keys are read by the app."""
        return {
            "duration": self.duration,
            "durationText": self.duration_text,
            "distance": self.distance,
        }


@dataclass(frozen=True)
class EtaData:
    """Both directions. 인사캠→자연캠 and back."""

    inja: EtaLeg | None
    jain: EtaLeg | None

    @property
    def complete(self) -> bool:
        return self.inja is not None and self.jain is not None

    def as_fields(self) -> dict[str, Any]:
        return {
            "inja": self.inja.as_fields() if self.inja else None,
            "jain": self.jain.as_fields() if self.jain else None,
        }


def directions_url(start: str, goal: str, *, base: str = NAVER_DIRECTIONS_URL) -> str:
    """Built here rather than passed as httpx `params` so the URL is one
    value the caller can log, cache-key or replay — the same reason
    `JongroRoute.list_url` builds its own."""
    return f"{base}?{urlencode({'start': start, 'goal': goal})}"


def format_duration(ms: float) -> str:
    """Milliseconds -> `"1시간 30분"` / `"1시간"` / `"30분"`.

    `js_round`, not Python's `round`: `Math.round` breaks ties away from
    zero and Python's breaks to even, so a duration of exactly 30.5
    minutes formats as 31분 in the TypeScript and 30분 here. Naver reports
    whole milliseconds, so half-minutes are reachable.

    Zero renders as `"0분"`, matching the TypeScript's final branch — the
    app shows a unit rather than an empty chip.
    """
    total_minutes = js_round(ms / 60_000)
    hours, minutes = divmod(total_minutes, 60)
    if hours > 0 and minutes > 0:
        return f"{hours}시간 {minutes}분"
    if hours > 0:
        return f"{hours}시간"
    return f"{minutes}분"


def read_leg(data: Any) -> EtaLeg:
    """Response -> one leg, or `CampusEtaPayloadError`.

    Every failure the TypeScript throws on is a failure here, with the
    same precedence: the envelope's own `code` is checked before the body,
    because Naver returns a well-formed body alongside a nonzero code.
    """
    if not isinstance(data, dict):
        raise CampusEtaPayloadError(
            f"expected a JSON object, got {type(data).__name__}"
        )

    code = data.get("code")
    # `isinstance(code, bool)` first, because Python's `False == 0` is True
    # and JavaScript's `false !== 0` is too. Without it a `code: false`
    # response would be read as success here and as an error by the
    # reference — the one branch where this port was more lenient than the
    # TypeScript it replaces.
    if isinstance(code, bool) or code != 0:
        raise CampusEtaPayloadError(
            f"Naver API error: code={code!r}, message={data.get('message')!r}"
        )

    route = data.get("route")
    routes = route.get("traoptimal") if isinstance(route, dict) else None
    first = routes[0] if isinstance(routes, list) and routes else None
    summary = first.get("summary") if isinstance(first, dict) else None
    if not isinstance(summary, dict):
        raise CampusEtaPayloadError(
            "response is missing route.traoptimal[0].summary"
        )

    duration = _non_negative_int(summary, "duration")
    distance = _non_negative_int(summary, "distance")
    return EtaLeg(
        duration=duration,
        duration_text=format_duration(duration),
        distance=distance,
    )


def _non_negative_int(summary: dict[str, Any], field: str) -> int:
    """Both values are counts (milliseconds, metres) and both flow into
    arithmetic — `format_duration`'s `divmod` in particular, where a
    negative would take Python's floor-modulo down a path JavaScript's
    sign-of-dividend remainder never goes. Refusing here means the
    disagreement is unreachable rather than merely unlikely.
    """
    value = summary.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CampusEtaPayloadError(
            f"summary.{field} is {value!r}, expected a number"
        )
    if value < 0:
        raise CampusEtaPayloadError(f"summary.{field} is negative: {value!r}")
    return int(value)
