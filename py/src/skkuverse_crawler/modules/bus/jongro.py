"""Jongro 02/07: the TOPIS envelope, the list transform, and dwell state.

Port of skkuverse-server's `jongro.poller.service.ts`. Two endpoints per
route, with very different characters:

- **list** — arrival board. A stateless field rename; every value the app
  shows (`eta`, `eventDate`) is copied through verbatim.
- **loc** — vehicle positions. Stateful: it tracks when each STATION was
  first seen occupied, so `estimatedTime` reports how long a bus has been
  sitting there.

Pure, like `hssc`: state arrives as an argument and leaves as a return
value. `outcome` is what makes the three upstream answers distinguishable
downstream — see `Outcome`.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping

from .registry import StationRef
from .time_ko import js_iso, js_round

# How long a station's occupancy clock survives without being refreshed.
# Past this the bus is assumed gone and the next sighting starts a new
# dwell rather than reporting an implausible one.
DWELL_EXPIRY = timedelta(minutes=10)

# "0" success, "4" no results (overnight, when nothing is running).
# Anything else is the upstream telling us it is broken.
SUCCESS_CODE = "0"
NO_RESULTS_CODE = "4"
USABLE_HEADER_CODES = frozenset({SUCCESS_CODE, NO_RESULTS_CODE})


class Outcome(enum.Enum):
    """Why a tick produced no items — the distinction the cache depends on.

    OK        -> write the items.
    NO_DATA   -> upstream said "nothing", or sent no itemList. Write
                 nothing; the previous document stands.
    UPSTREAM_ERROR -> a header code we do not accept. Same: write nothing.

    Collapsing NO_DATA and UPSTREAM_ERROR into "empty list" would publish
    "no buses are running" every time TOPIS has an outage.
    """

    OK = "ok"
    NO_DATA = "no_data"
    UPSTREAM_ERROR = "upstream_error"


@dataclass(frozen=True)
class Envelope:
    outcome: Outcome
    items: list[dict[str, Any]]
    header_code: str | None = None


def read_envelope(data: Any) -> Envelope:
    """Unwrap `{msgHeader:{headerCd}, msgBody:{itemList}}`.

    The header is checked before the body because a broken upstream still
    sends a body — often the previous, stale one.
    """
    if not isinstance(data, dict):
        return Envelope(Outcome.UPSTREAM_ERROR, [], header_code=None)

    header = data.get("msgHeader")
    code = header.get("headerCd") if isinstance(header, dict) else None
    # Falsy codes ("" , None, 0, False) skip the check and the body is
    # published. That is not leniency for its own sake — it is what the
    # TypeScript does (`if (cd && !isUsableHeaderCd(cd))`), and treating ""
    # as an error would freeze the stored document while the upstream is
    # still sending buses. Every captured tick carries "0" or "4", so the
    # fixtures cannot decide this either way; the reference does.
    if code and str(code) not in USABLE_HEADER_CODES:
        return Envelope(Outcome.UPSTREAM_ERROR, [], header_code=str(code))

    body = data.get("msgBody")
    items = body.get("itemList") if isinstance(body, dict) else None
    if not isinstance(items, list):
        # Null itemList is how "4" arrives overnight, and also what a
        # truncated response looks like. Neither is a reason to publish.
        return Envelope(
            Outcome.NO_DATA, [], header_code=str(code) if code is not None else None
        )
    return Envelope(
        Outcome.OK, items, header_code=str(code) if code is not None else None
    )


def _car_number(plate: Any) -> str:
    """Last four of the plate, or a placeholder.

    The app shows this on the vehicle chip; an empty string there renders
    as a blank badge, so the upstream's missing value gets a visible one.
    """
    return str(plate or "").strip()[-4:] or "----"


def normalize_list(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Arrival board rows -> the `jongro_stations_<code>` payload.

    Deliberately no filtering and no derived times: `eta` is a
    human-readable Korean string the app renders as-is, and `eventDate`
    is the upstream's own stamp in its own format. Reformatting either
    would be this port inventing a difference.
    """
    return [
        {
            "stationId": str(item.get("stId", "")),
            "sequence": str(item.get("staOrd", "")),
            "stationName": str(item.get("stNm", "")),
            "carNumber": _car_number(item.get("plainNo1")),
            "eventDate": str(item.get("mkTm", "")),
            "stationNumber": str(item.get("arsId", "")),
            "eta": str(item.get("arrmsg1", "")),
        }
        for item in items
    ]


def normalize_loc(
    previous: Mapping[str, str],
    items: list[dict[str, Any]],
    mapping: Mapping[str, StationRef],
    *,
    now: datetime,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Positions -> the `jongro_locations_<code>` payload, and next state.

    `previous` maps a station id to when a bus was first seen there, as an
    ISO-8601 UTC string. Returned rather than mutated so a caller cannot
    accidentally share it.

    The clock is keyed by STATION, not by vehicle — that is the upstream
    design, and it means two buses at one station share a dwell reading.
    An entry older than `DWELL_EXPIRY` is discarded and re-recorded, so
    `estimatedTime` runs 0, 40, 80 … up to the expiry and then resets.

    An unmapped `lastStnId` is dropped: the registry is the authority on
    which stations belong to a route, and a position we cannot place has
    no sequence to render against.
    """
    state = dict(previous)
    stamp = js_iso(now)

    rows: list[dict[str, Any]] = []
    for item in items:
        station_id = str(item.get("lastStnId", ""))
        station = mapping.get(station_id)
        if station is None:
            continue

        recorded = state.get(station_id)
        if recorded is not None and _older_than_expiry(recorded, now=now):
            del state[station_id]
            recorded = None

        if recorded is None:
            state[station_id] = stamp
            estimated = 0
            record_time = stamp
        else:
            estimated = js_round((now - _parse_iso(recorded)).total_seconds())
            record_time = recorded

        rows.append(
            {
                "sequence": str(station.sequence),
                "stationName": station.station_name,
                "carNumber": _car_number(item.get("plainNo")),
                "eventDate": record_time,
                "estimatedTime": estimated,
                "stationId": station_id,
                # tmY is latitude and tmX longitude — swapped relative to
                # the usual x/y intuition, which is why they are named
                # here rather than passed through positionally.
                "latitude": str(item.get("tmY", "")),
                "longitude": str(item.get("tmX", "")),
                "recordTime": record_time,
            }
        )
    return rows, state




def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _older_than_expiry(recorded: str, *, now: datetime) -> bool:
    return (now - _parse_iso(recorded)) > DWELL_EXPIRY
