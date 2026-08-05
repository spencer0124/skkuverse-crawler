"""Jongro route registry — package data, validated fail-loud at load.

Ported from skkuverse-server's `jongro-registry.ts`, including its
validation. That validation is the point: the fetcher needs
`topisId → (sequence, stationName)` to make sense of an upstream response,
and a route file with a duplicate or missing `topisId` does not fail — it
silently drops every position report for that station, which looks
exactly like "no bus is there".

Read with `importlib.resources`, not an env var path. `sources.json` needs
`SOURCES_JSON_PATH` because the container mounts it and it changes without
a code change; routes change only *with* a code change, so a path override
would buy the loader's shadowing problem for nothing — and would force a
third entry into a two-entry allowlist whose docstring is an apology for
having two.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from types import MappingProxyType
from typing import Any, Mapping

ROUTES_FILE = "jongro-routes.json"

# Route ids are "jongro" + a zero-padded or multi-digit number. The pattern
# exists so that cache keys cannot collide: without it "jongro7" and
# "jongro07" would both yield suffix "7"/"07" ambiguously.
ID_PATTERN = re.compile(r"^jongro(0[1-9]|[1-9]\d+)$")
_HEX6 = re.compile(r"^[0-9A-Fa-f]{6}$")
# The upstream takes the key in a query string, so it must already be
# URL-encoded; an unencoded "+" or "/" silently authenticates as a
# different (nonexistent) key and every request comes back an error.
SERVICE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_%-]+$")

SEOUL_BUS_BASE = "http://ws.bus.go.kr/api/rest"


class RouteConfigError(ValueError):
    """The route registry is unusable. Raised at load, never mid-crawl."""


@dataclass(frozen=True)
class StationRef:
    """What a position report resolves to once mapped."""

    sequence: int
    station_name: str


@dataclass(frozen=True)
class JongroRoute:
    id: str
    code: str
    bus_route_id: str
    station_count: int
    # topisId -> StationRef. Frozen so a fetcher cannot mutate the registry.
    mapping: Mapping[str, StationRef]

    def list_url(self, service_key: str, *, base: str = SEOUL_BUS_BASE) -> str:
        return (
            f"{base}/arrive/getArrInfoByRouteAll"
            f"?serviceKey={service_key}&busRouteId={self.bus_route_id}&resultType=json"
        )

    def loc_url(self, service_key: str, *, base: str = SEOUL_BUS_BASE) -> str:
        return (
            f"{base}/buspos/getBusPosByRouteSt"
            f"?serviceKey={service_key}&busRouteId={self.bus_route_id}"
            f"&startOrd=1&endOrd={self.station_count}&resultType=json"
        )


def validate_service_key(key: str | None) -> None:
    """Refuse a key that is not URL-encoded.

    Checked separately from the routes because it comes from `Config`
    rather than from package data, and because the failure it prevents is
    invisible: an unencoded key produces a well-formed request that simply
    never authenticates.
    """
    if not key:
        raise RouteConfigError("SEOUL_BUS_SERVICE_KEY is not set")
    if not SERVICE_KEY_PATTERN.match(key):
        raise RouteConfigError(
            "SEOUL_BUS_SERVICE_KEY must be URL-encoded "
            "(allowed characters: A-Z a-z 0-9 _ % -)"
        )


def validate_routes(raw: Any) -> list[str]:
    """Every problem at once, so one load fixes them all rather than one
    per attempt. Returns messages; the caller decides to raise."""
    errors: list[str] = []
    if not isinstance(raw, list):
        return [f"{ROUTES_FILE} must be a JSON array"]

    seen_ids: set[str] = set()
    for i, route in enumerate(raw):
        where = f"routes[{i}]"
        if not isinstance(route, dict):
            errors.append(f"{where}: not an object")
            continue

        route_id = route.get("id")
        if not isinstance(route_id, str) or not ID_PATTERN.match(route_id):
            errors.append(f"{where}.id: must match {ID_PATTERN.pattern}")
        elif route_id in seen_ids:
            errors.append(f'{where}.id: duplicate "{route_id}"')
        else:
            seen_ids.add(route_id)

        if not _nonempty_str(route.get("busRouteId")):
            errors.append(f"{where}.busRouteId: required non-empty string")
        theme = route.get("themeColor")
        if not isinstance(theme, str) or not _HEX6.match(theme):
            errors.append(f"{where}.themeColor: must be a 6-character hex string")

        stations = route.get("stations")
        if not isinstance(stations, list) or not stations:
            errors.append(f"{where}.stations: required non-empty array")
            continue

        # `sequence` is derived from array position (see _build), so the
        # order of this list is load-bearing. The TS validates the same
        # invariants for the same reason: reorder the array and every bus
        # renders against the wrong station name, with nothing raising.
        first_at = [j for j, s in enumerate(stations) if _flag(s, "isFirstStation")]
        last_at = [j for j, s in enumerate(stations) if _flag(s, "isLastStation")]
        if first_at != [0]:
            errors.append(
                f"{where}.stations: exactly one isFirstStation, at index 0 "
                f"(found at {first_at})"
            )
        if last_at != [len(stations) - 1]:
            errors.append(
                f"{where}.stations: exactly one isLastStation, at the end "
                f"(found at {last_at})"
            )

        seen_topis: set[str] = set()
        for j, station in enumerate(stations):
            spot = f"{where}.stations[{j}]"
            if not isinstance(station, dict):
                errors.append(f"{spot}: not an object")
                continue
            if not _nonempty_str(station.get("stationName")):
                errors.append(f"{spot}.stationName: required non-empty string")
            if not _nonempty_str(station.get("arsId")):
                errors.append(f"{spot}.arsId: required non-empty string")
            topis = station.get("topisId")
            if not _nonempty_str(topis):
                errors.append(f"{spot}.topisId: required non-empty string")
            elif topis in seen_topis:
                # The mapping is keyed on this, so a duplicate does not
                # error — it shadows, and one station's buses vanish.
                errors.append(f'{spot}.topisId: duplicate "{topis}" within route')
            else:
                seen_topis.add(str(topis))
    return errors


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


def _flag(station: Any, name: str) -> bool:
    return isinstance(station, dict) and station.get(name) is True


def _build(raw: dict[str, Any]) -> JongroRoute:
    stations = raw["stations"]
    return JongroRoute(
        id=raw["id"],
        # "jongro07" -> "07". This suffix IS the cache key's, so it must
        # keep matching what skkuverse-server derives the same way.
        code=raw["id"][len("jongro") :],
        bus_route_id=raw["busRouteId"],
        station_count=len(stations),
        mapping=MappingProxyType(
            {
                s["topisId"]: StationRef(sequence=i + 1, station_name=s["stationName"])
                for i, s in enumerate(stations)
            }
        ),
    )


def load_routes(raw: Any | None = None) -> tuple[JongroRoute, ...]:
    """Load and validate. `raw` is for tests; production reads package data."""
    if raw is None:
        text = (
            resources.files("skkuverse_crawler.modules.bus")
            .joinpath(ROUTES_FILE)
            .read_text(encoding="utf-8")
        )
        raw = json.loads(text)
    errors = validate_routes(raw)
    if errors:
        raise RouteConfigError(
            f"{ROUTES_FILE} is invalid:\n  - " + "\n  - ".join(errors)
        )
    return tuple(_build(r) for r in raw)


def route_by_code(routes: tuple[JongroRoute, ...], code: str) -> JongroRoute:
    for route in routes:
        if route.code == code:
            return route
    raise RouteConfigError(
        f"no route with code {code!r} (known: {', '.join(r.code for r in routes)})"
    )
