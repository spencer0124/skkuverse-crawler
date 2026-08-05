"""The migration's actual acceptance test.

Bus is moving out of skkuverse-server. Its API reads `bus_cache` documents
by field name, so "the Python normaliser produces the same payload the
TypeScript poller produced" is not a nice-to-have — it is the whole
correctness criterion, and nothing else in this repo can check it.

The expected values in `tests/fixtures/bus/` were produced by executing
the server's compiled transforms over its captured upstream responses
(see that directory's README and `py/scripts/generate_bus_goldens.js`).
These tests replay the same captures through the Python port and demand
equality.

Replay is per-day and in order, against one carried state, because both
pollers are stateful. Comparing tick-by-tick in isolation would pass with
the sticky-timestamp and dwell logic completely absent.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import pytest

from skkuverse_crawler.modules.bus import hssc, jongro
from skkuverse_crawler.modules.bus.registry import load_routes, route_by_code

FIXTURES = Path(__file__).parents[1] / "fixtures" / "bus"
# parents: [0] bus  [1] tests  [2] py  [3] repo root
CRAWLER_ROOT = Path(__file__).parents[3]
SERVER_CAPTURES = CRAWLER_ROOT.parent / "skkuverse-server" / "__fixtures__"

ROUTES = load_routes()


def _goldens(api: str) -> list[Path]:
    return sorted((FIXTURES / api).glob("*.json"))


@lru_cache(maxsize=None)
def _captures(day: str, api: str) -> tuple[dict, ...]:
    """The raw upstream responses the goldens were generated from.

    Cached: the dense tests scan every day looking for one capture, and
    each parametrised day is re-read by its own test. Without this the
    suite spends most of its time re-parsing the same ~11MB of JSON.
    Returned as a tuple so a caller cannot mutate the cached value.
    """
    directory = SERVER_CAPTURES / day / api
    return tuple(
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    )


@lru_cache(maxsize=None)
def _days() -> tuple[str, ...]:
    if not SERVER_CAPTURES.is_dir():
        return ()
    return tuple(sorted(p.name for p in SERVER_CAPTURES.iterdir() if p.is_dir()))


@lru_cache(maxsize=None)
def _golden_rows(path_str: str) -> list[dict]:
    return json.loads(Path(path_str).read_text(encoding="utf-8"))


def _at(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp)


def _response(capture: dict):
    """The upstream response, or None if the capture never got one.

    Some captures record the RECORDER's failure — `{"status": "error",
    "error": "timeout of 15000ms exceeded"}` with no `data` at all. That is
    a transport failure, not a response, and it is not the normaliser's
    business: in production axios raises, the poller's try/except swallows
    it, and nothing is written. The golden records null, and the fetch
    layer added in a later phase is what will raise here.
    """
    if capture.get("status") != "success" or "data" not in capture:
        return None
    return capture["data"]


needs_captures = pytest.mark.skipif(
    not SERVER_CAPTURES.is_dir(),
    reason=(
        "skkuverse-server/__fixtures__ not present — these replay its raw "
        "captures. The goldens alone are not enough: they are the expected "
        "OUTPUT, and the input lives in the sibling repo."
    ),
)


# ── HSSC ──────────────────────────────────────────────────────────────────


@needs_captures
@pytest.mark.parametrize("golden", _goldens("hssc"), ids=lambda p: p.stem)
def test_hssc_matches_the_typescript_day_for_day(golden: Path):
    expected = _golden_rows(str(golden))
    captures = _captures(golden.stem, "hssc")
    assert len(captures) == len(expected), "golden and capture counts disagree"

    carried: list[dict] = []
    for tick, (capture, want) in enumerate(zip(captures, expected)):
        data = _response(capture)
        if data is None:
            assert want["payload"] is None, f"tick {tick} ({capture['timestamp']})"
            continue
        rows = hssc.parse(data)
        if rows is None:
            # A non-array response: the poller writes nothing and the
            # previous document stands. The golden records that as null.
            assert want["payload"] is None, f"tick {tick} ({capture['timestamp']})"
            continue
        got = hssc.normalize(carried, rows, now=_at(capture["timestamp"]))
        assert got == want["payload"], f"tick {tick} at {capture['timestamp']}"
        carried = got


# ── Jongro ────────────────────────────────────────────────────────────────


@needs_captures
@pytest.mark.parametrize("code", ["02", "07"])
def test_jongro_list_matches_the_typescript(code: str):
    goldens = _goldens(f"jongro{code}_list")
    assert goldens, "no goldens found — a rename or partial checkout would "
    compared = 0
    for golden in goldens:
        expected = _golden_rows(str(golden))
        captures = _captures(golden.stem, f"jongro{code}_list")
        assert len(captures) == len(expected)

        for tick, (capture, want) in enumerate(zip(captures, expected)):
            where = f"{golden.stem} tick {tick} at {capture['timestamp']}"
            data = _response(capture)
            if data is None:
                assert want["payload"] is None, where
                continue
            envelope = jongro.read_envelope(data)
            if envelope.outcome is not jongro.Outcome.OK:
                assert want["payload"] is None, where
                continue
            assert jongro.normalize_list(envelope.items) == want["payload"], where
            compared += 1
    # Without this the loop above passes with zero iterations, and four
    # tests become no-ops on a directory rename with no signal at all.
    assert compared > 0, "matched no ticks"


@needs_captures
@pytest.mark.parametrize("code", ["02", "07"])
def test_jongro_loc_matches_the_typescript(code: str):
    route = route_by_code(ROUTES, code)
    goldens = _goldens(f"jongro{code}_loc")
    assert goldens, "no goldens found"
    compared = 0
    for golden in goldens:
        expected = _golden_rows(str(golden))
        captures = _captures(golden.stem, f"jongro{code}_loc")
        assert len(captures) == len(expected)

        state: dict[str, str] = {}
        for tick, (capture, want) in enumerate(zip(captures, expected)):
            where = f"{golden.stem} tick {tick} at {capture['timestamp']}"
            data = _response(capture)
            if data is None:
                assert want["payload"] is None, where
                continue
            envelope = jongro.read_envelope(data)
            if envelope.outcome is not jongro.Outcome.OK:
                assert want["payload"] is None, where
                continue
            rows, state = jongro.normalize_loc(
                state, envelope.items, route.mapping, now=_at(capture["timestamp"])
            )
            assert rows == want["payload"], where
            compared += 1
    assert compared > 0, "matched no ticks"


# ── the dense replays ─────────────────────────────────────────────────────
#
# The captures are 30 minutes apart while Jongro's dwell clock expires
# after 10, so the real corpus above never reaches the accumulation path —
# every tick re-records and reports 0. These replay ONE real capture at the
# production tick interval, which is where the stateful logic actually
# lives. Without them the dwell code could be deleted and everything above
# would still pass.


def _dense(name: str) -> dict:
    return json.loads((FIXTURES / "_dense" / f"{name}.json").read_text("utf-8"))


def test_dense_hssc_reproduces_the_sticky_timestamp_climb():
    """Runs everywhere: the capture is embedded in the golden.

    That matters more than it sounds. The day-by-day tests above need
    skkuverse-server checked out beside this repo and skip without it,
    which means CI runs none of them. These three are the parity coverage
    CI actually gets — and they happen to be the ones covering the
    stateful paths.
    """
    dense = _dense("hssc")
    carried: list[dict] = []
    compared = 0
    for tick, want in enumerate(dense["rows"]):
        rows = hssc.parse(dense["capture"])
        assert rows is not None
        got = hssc.normalize(carried, rows, now=_at(want["at"]))
        assert got == want["payload"], f"dense tick {tick} at {want['at']}"
        carried = got
        compared += 1
    assert compared == len(dense["rows"]) > 1

    # Guard the guard: if this stopped exercising the sticky path the
    # assertions above would keep passing while proving nothing.
    series = [
        item["estimatedTime"]
        for row in dense["rows"]
        for item in (row["payload"] or [])
    ]
    assert any(b > a for a, b in zip(series, series[1:])), (
        "the dense HSSC replay no longer shows estimatedTime accumulating — "
        "regenerate the goldens"
    )


@pytest.mark.parametrize("code", ["02", "07"])
def test_dense_jongro_loc_reproduces_the_dwell_cycle(code: str):
    """The only coverage anywhere of dwell accumulation and its expiry.

    The real captures are 30 minutes apart while the clock expires after
    10, so every one of the 775 ticks above re-records and reports 0 —
    delete the dwell logic and they all still pass.
    """
    dense = _dense(f"jongro{code}_loc")
    route = route_by_code(ROUTES, code)

    envelope = jongro.read_envelope(dense["capture"])
    assert envelope.outcome is jongro.Outcome.OK

    state: dict[str, str] = {}
    for tick, want in enumerate(dense["rows"]):
        rows, state = jongro.normalize_loc(
            state, envelope.items, route.mapping, now=_at(want["at"])
        )
        assert rows == want["payload"], f"dense tick {tick} at {want['at']}"

    tracked = dense["rows"][0]["payload"][0]["stationId"]
    series = [
        item["estimatedTime"]
        for row in dense["rows"]
        for item in (row["payload"] or [])
        if item["stationId"] == tracked
    ]
    assert any(b > a for a, b in zip(series, series[1:])), "no accumulation observed"
    assert any(b < a for a, b in zip(series, series[1:])), (
        "no dwell expiry observed — the replay no longer crosses DWELL_EXPIRY"
    )
