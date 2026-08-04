"""The parts a fixture replay cannot reach.

The parity suite proves the port matches the TypeScript over a month of
real captures, which is the strong evidence. It cannot cover what the
captures happen not to contain — the 12-hour meridiem boundary, a
malformed route file, an upstream error code that never occurred — and
those are exactly the cases where being wrong looks like plausible data.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from skkuverse_crawler.modules.bus import hssc, jongro
from skkuverse_crawler.modules.bus.registry import (
    RouteConfigError,
    StationRef,
    load_routes,
    route_by_code,
    validate_routes,
    validate_service_key,
)
from skkuverse_crawler.modules.bus.sources import BusSource, CacheKey, shadow
from skkuverse_crawler.modules.bus.time_ko import (
    KST,
    KoreanTimeFormatError,
    format_stamp,
    parse_korean,
    parse_stamp,
)


class TestKoreanMeridiem:
    """오전 12시 is midnight and 오후 12시 is noon.

    Getting this backwards moves two hours of every day by twelve hours,
    which reads as real data — a bus that "arrived" at 00:15 instead of
    12:15 is not obviously wrong to anyone reading a log.
    """

    @pytest.mark.parametrize(
        "text,expected_hour",
        [
            ("2026-03-16 오전 12:00:00", 0),
            ("2026-03-16 오전 1:00:00", 1),
            ("2026-03-16 오전 11:59:59", 11),
            ("2026-03-16 오후 12:00:00", 12),
            ("2026-03-16 오후 1:00:00", 13),
            ("2026-03-16 오후 11:59:59", 23),
        ],
    )
    def test_the_twelve_hour_boundary(self, text, expected_hour):
        assert parse_korean(text).hour == expected_hour

    def test_it_is_kst_not_utc(self):
        assert parse_korean("2026-03-16 오전 8:58:46").utcoffset() == timedelta(hours=9)

    def test_an_unpadded_hour_parses(self):
        """The upstream writes 8, not 08."""
        assert parse_korean("2026-03-16 오전 8:58:46").hour == 8

    @pytest.mark.parametrize(
        "bad",
        [
            "2026-03-16 08:58:46",  # no meridiem
            "2026-03-16 AM 8:58:46",  # already translated
            "2026/03/16 오전 8:58:46",  # different separators
            "2026-03-16 오전 13:00:00",  # not a 12-hour clock
            "",
        ],
    )
    def test_a_shape_it_does_not_know_raises_naming_the_value(self, bad):
        """Loud, because "upstream changed its format" must not arrive as a
        swallowed ValueError three frames up."""
        with pytest.raises(KoreanTimeFormatError):
            parse_korean(bad)

    def test_no_tzdata_is_required(self):
        """zoneinfo would raise on a slim image with no /usr/share/zoneinfo.
        Korea has had no DST since 1988, so a fixed offset is exact."""
        assert KST.utcoffset(None) == timedelta(hours=9)

    def test_round_trip_through_the_stored_format(self):
        parsed = parse_korean("2026-03-16 오후 3:04:05")
        assert format_stamp(parsed) == "2026-03-16 15:04:05"
        assert parse_stamp(format_stamp(parsed)) == parsed

    def test_parse_stamp_refuses_a_raw_upstream_string(self):
        """The two parsers are separate so a raw value cannot flow into the
        slot that holds a normalised one."""
        with pytest.raises(KoreanTimeFormatError):
            parse_stamp("2026-03-16 오전 8:58:46")


class TestLinearSequence:
    def test_the_circle_is_rotated_not_shifted(self):
        """Upstream seq 0-10; the app wants 1-11 starting elsewhere on the
        circle, so the two halves swap rather than slide."""
        assert [hssc.linear_sequence(s) for s in range(11)] == [
            7, 8, 9, 10, 11, 1, 2, 3, 4, 5, 6,
        ]

    def test_every_position_is_used_exactly_once(self):
        assert sorted(hssc.linear_sequence(s) for s in range(11)) == list(range(1, 12))


class TestHsscParse:
    def test_a_non_list_is_none_not_an_empty_list(self):
        """None means "write nothing, the stored document stands"; [] means
        "no buses are running". Collapsing them publishes an outage as a
        service announcement."""
        assert hssc.parse({"error": "nope"}) is None
        assert hssc.parse(None) is None
        assert hssc.parse([]) == []

    def test_a_missing_field_names_itself(self):
        with pytest.raises(hssc.HsscPayloadError, match="stop_name"):
            hssc.parse([{"line_no": "1", "inout": "x", "stop_no": "2", "seq": "0",
                         "get_date": "2026-03-16 오전 8:00:00"}])


class TestHsscStaleFilter:
    @staticmethod
    def _row(stop_name="성균관대입구사거리", get_date="2026-03-16 오전 9:00:00"):
        return hssc.HsscRow("32072", "ENTERED", "284434", "5", stop_name, get_date)

    def test_a_fresh_sighting_survives(self):
        now = datetime(2026, 3, 16, 9, 5, tzinfo=KST)
        assert len(hssc.normalize([], [self._row()], now=now)) == 1

    def test_the_turnaround_stop_has_a_tighter_window(self):
        """A bus waits at the turnaround between runs, so the default
        10-minute window would keep reporting one that has already left."""
        now = datetime(2026, 3, 16, 9, 5, tzinfo=KST)
        turnaround = self._row(stop_name="농구장정류소")  # maps to the turnaround
        assert hssc.normalize([], [turnaround], now=now) == []
        assert len(hssc.normalize([], [self._row()], now=now)) == 1

    def test_stale_everywhere_yields_an_empty_list_not_none(self):
        """This is how "no buses are running" is expressed — the upstream
        never says it, because it pins its last rows indefinitely."""
        now = datetime(2026, 3, 16, 10, 0, tzinfo=KST)
        assert hssc.normalize([], [self._row()], now=now) == []


class TestHsscStickyTimestamp:
    @staticmethod
    def _row(get_date):
        return hssc.HsscRow("32072", "ENTERED", "284434", "5", "성균관대입구사거리", get_date)

    def test_a_returning_bus_keeps_its_first_sighting(self):
        """estimatedTime is a dwell time. Re-reading get_date every tick
        would reset it to ~0 forever and the app could never show "has been
        here 4 minutes"."""
        first_at = datetime(2026, 3, 16, 9, 0, tzinfo=KST)
        first = hssc.normalize([], [self._row("2026-03-16 오전 9:00:00")], now=first_at)
        assert first[0]["estimatedTime"] == 0

        later = hssc.normalize(
            first,
            # Upstream has moved its own stamp on; the sticky one wins.
            [self._row("2026-03-16 오전 9:03:00")],
            now=first_at + timedelta(minutes=3),
        )
        assert later[0]["estimatedTime"] == 180
        assert later[0]["eventDate"] == first[0]["eventDate"]

    def test_a_bus_that_aged_out_starts_fresh(self):
        """`previous` is the POST-filter list, so a dropped bus loses its
        sticky stamp. That is the upstream behaviour, not an oversight."""
        stale = hssc.normalize(
            [], [self._row("2026-03-16 오전 9:00:00")],
            now=datetime(2026, 3, 16, 9, 30, tzinfo=KST),
        )
        assert stale == []
        fresh = hssc.normalize(
            stale, [self._row("2026-03-16 오전 9:31:00")],
            now=datetime(2026, 3, 16, 9, 31, tzinfo=KST),
        )
        assert fresh[0]["estimatedTime"] == 0


class TestJongroEnvelope:
    @pytest.mark.parametrize("code", ["0", "4"])
    def test_success_and_no_results_are_both_usable(self, code):
        """"4" is overnight, when nothing runs — not an error."""
        envelope = jongro.read_envelope(
            {"msgHeader": {"headerCd": code}, "msgBody": {"itemList": []}}
        )
        assert envelope.outcome is jongro.Outcome.OK

    @pytest.mark.parametrize("code", ["1", "5", "500"])
    def test_any_other_code_is_an_upstream_error(self, code):
        envelope = jongro.read_envelope(
            {"msgHeader": {"headerCd": code}, "msgBody": {"itemList": [{"a": 1}]}}
        )
        assert envelope.outcome is jongro.Outcome.UPSTREAM_ERROR
        assert envelope.items == []

    def test_a_null_itemList_is_no_data_not_an_error(self):
        """How "4" actually arrives overnight — 366 of the captured ticks
        for jongro07 look like this."""
        envelope = jongro.read_envelope(
            {"msgHeader": {"headerCd": "4"}, "msgBody": {"itemList": None}}
        )
        assert envelope.outcome is jongro.Outcome.NO_DATA

    def test_a_non_dict_response_is_an_error(self):
        assert jongro.read_envelope("<html>").outcome is jongro.Outcome.UPSTREAM_ERROR

    def test_the_header_is_judged_before_the_body(self):
        """A broken upstream still sends a body, often the previous one."""
        envelope = jongro.read_envelope(
            {"msgHeader": {"headerCd": "500"}, "msgBody": {"itemList": [{"a": 1}]}}
        )
        assert envelope.outcome is jongro.Outcome.UPSTREAM_ERROR


class TestJongroDwell:
    MAPPING = {"S1": StationRef(sequence=3, station_name="혜화역")}

    def _item(self, plate="12가3456"):
        return {"lastStnId": "S1", "tmY": "37.5", "tmX": "127.0", "plainNo": plate}

    def test_first_sighting_reports_zero_and_records(self):
        now = datetime(2026, 3, 16, 9, 0, tzinfo=KST)
        rows, state = jongro.normalize_loc({}, [self._item()], self.MAPPING, now=now)
        assert rows[0]["estimatedTime"] == 0
        assert "S1" in state

    def test_it_accumulates_while_the_bus_stays(self):
        now = datetime(2026, 3, 16, 9, 0, tzinfo=KST)
        _, state = jongro.normalize_loc({}, [self._item()], self.MAPPING, now=now)
        rows, _ = jongro.normalize_loc(
            state, [self._item()], self.MAPPING, now=now + timedelta(seconds=40)
        )
        assert rows[0]["estimatedTime"] == 40

    def test_it_resets_past_the_expiry(self):
        """Past 10 minutes the bus is assumed gone, so the next sighting
        starts a new dwell rather than reporting an implausible one."""
        now = datetime(2026, 3, 16, 9, 0, tzinfo=KST)
        _, state = jongro.normalize_loc({}, [self._item()], self.MAPPING, now=now)
        rows, _ = jongro.normalize_loc(
            state,
            [self._item()],
            self.MAPPING,
            now=now + jongro.DWELL_EXPIRY + timedelta(seconds=1),
        )
        assert rows[0]["estimatedTime"] == 0

    def test_the_caller_state_is_not_mutated(self):
        """Returned rather than mutated so two routes cannot share a map by
        accident — they are separate services in production."""
        now = datetime(2026, 3, 16, 9, 0, tzinfo=KST)
        original: dict[str, str] = {}
        jongro.normalize_loc(original, [self._item()], self.MAPPING, now=now)
        assert original == {}

    def test_an_unmapped_station_is_dropped(self):
        """The registry is the authority on which stations belong to a
        route; a position we cannot place has no sequence to render."""
        now = datetime(2026, 3, 16, 9, 0, tzinfo=KST)
        rows, _ = jongro.normalize_loc(
            {}, [{"lastStnId": "NOPE", "tmY": "1", "tmX": "2"}], self.MAPPING, now=now
        )
        assert rows == []

    def test_a_missing_plate_gets_a_visible_placeholder(self):
        now = datetime(2026, 3, 16, 9, 0, tzinfo=KST)
        rows, _ = jongro.normalize_loc({}, [self._item(plate="")], self.MAPPING, now=now)
        assert rows[0]["carNumber"] == "----"

    def test_the_timestamp_matches_javascript_toISOString(self):
        """Three-digit milliseconds and a literal Z. Python's isoformat
        drops the fraction when it is zero — which is every timestamp here —
        and the app compares these as strings."""
        now = datetime(2026, 3, 16, 9, 0, tzinfo=KST)
        rows, _ = jongro.normalize_loc({}, [self._item()], self.MAPPING, now=now)
        assert rows[0]["recordTime"] == "2026-03-16T00:00:00.000Z"


class TestRegistry:
    def test_the_shipped_routes_load(self):
        routes = load_routes()
        assert {r.code for r in routes} == {"02", "07"}

    def test_the_code_is_what_cache_keys_are_built_from(self):
        """skkuverse-server derives the same suffix the same way; if these
        drift the crawler writes documents the server never reads."""
        route = route_by_code(load_routes(), "07")
        assert route.id == "jongro07"
        assert CacheKey.jongro_stations(route.code) is CacheKey.JONGRO_STATIONS_07
        assert CacheKey.jongro_locations(route.code) is CacheKey.JONGRO_LOCATIONS_07

    def test_the_mapping_is_one_based_and_ordered(self):
        route = route_by_code(load_routes(), "02")
        sequences = sorted(ref.sequence for ref in route.mapping.values())
        assert sequences == list(range(1, len(sequences) + 1))

    def test_the_mapping_cannot_be_mutated(self):
        route = route_by_code(load_routes(), "02")
        with pytest.raises(TypeError):
            route.mapping["X"] = StationRef(1, "nope")  # type: ignore[index]

    def test_a_duplicate_topis_id_is_refused(self):
        """It would not error — it would shadow, and one station's buses
        would silently disappear from the map."""
        station = {"stationName": "A", "arsId": "1", "topisId": "SAME"}
        errors = validate_routes(
            [{
                "id": "jongro02", "busRouteId": "1", "themeColor": "abcdef",
                "iconType": "bus", "refreshInterval": 40,
                "stations": [station, dict(station, stationName="B", arsId="2")],
            }]
        )
        assert any("duplicate" in e for e in errors)

    def test_every_problem_is_reported_at_once(self):
        errors = validate_routes([{"id": "nope", "themeColor": "zzz"}])
        assert len(errors) >= 3

    def test_a_bad_file_raises_rather_than_degrading(self):
        with pytest.raises(RouteConfigError):
            load_routes(raw={"not": "a list"})


class TestServiceKey:
    def test_an_unencoded_key_is_refused(self):
        """An unencoded + or / produces a well-formed request that simply
        never authenticates — every response an error, no clue why."""
        with pytest.raises(RouteConfigError, match="URL-encoded"):
            validate_service_key("abc/def+ghi")

    def test_an_encoded_key_passes(self):
        validate_service_key("abc%2Fdef-ghi_123")

    @pytest.mark.parametrize("missing", [None, ""])
    def test_absent_is_refused_separately(self, missing):
        with pytest.raises(RouteConfigError, match="not set"):
            validate_service_key(missing)


class TestTypedKeys:
    def test_module_names_are_the_selector_and_the_health_identity(self):
        assert BusSource.HSSC.value == "bus-hssc"
        assert BusSource("bus-jongro") is BusSource.JONGRO

    def test_an_unknown_name_raises(self):
        with pytest.raises(ValueError):
            BusSource("bus-typo")

    def test_cache_keys_are_str_so_they_drop_into_mongo_filters(self):
        assert CacheKey.HSSC == "hssc"
        assert f"{CacheKey.HSSC.value}" == "hssc"

    def test_shadow_keys_are_derived_never_written_by_hand(self):
        """A typo here writes a document the comparison step would then
        silently fail to find."""
        assert shadow(CacheKey.HSSC) == "hssc__shadow"
        assert shadow(CacheKey.JONGRO_LOCATIONS_07) == "jongro_locations_07__shadow"


class TestDivergencesFoundByReview:
    """Each of these is a place the port and the TypeScript disagreed, and
    that the 775-tick corpus structurally could not expose."""

    def test_a_falsy_header_code_publishes_rather_than_freezing(self):
        """TS is `if (cd && !isUsableHeaderCd(cd))` — a falsy code
        short-circuits and the body IS published. Treating "" as an error
        would freeze the stored document while the upstream is still
        sending buses, silently and indefinitely.

        Every captured tick carries "0" or "4", so the fixtures cannot
        decide this either way; the reference implementation does.
        """
        for falsy in ("", None, 0, False):
            envelope = jongro.read_envelope(
                {"msgHeader": {"headerCd": falsy}, "msgBody": {"itemList": [{"a": 1}]}}
            )
            assert envelope.outcome is jongro.Outcome.OK, f"headerCd={falsy!r}"

    def test_rounding_goes_away_from_zero_like_javascript(self):
        """Python's round() is banker's rounding: round(40.5) == 40, where
        Math.round(40.5) == 41. Every fixture timestamp is whole-second so
        no golden can catch it, but production `now` carries milliseconds
        and lands on an exact .5 about once in a thousand ticks."""
        from skkuverse_crawler.modules.bus.time_ko import js_round

        assert [js_round(v) for v in (0.5, 1.5, 2.5, 40.5)] == [1, 2, 3, 41]
        assert [round(v) for v in (0.5, 2.5, 40.5)] == [0, 2, 40]  # what we avoid

    def test_the_sticky_lookup_takes_the_first_match(self):
        """TS uses Array.find. A dict comprehension would let a later
        duplicate win, and two buses of one line at one stop differ by the
        entire dwell time, not by a rounding."""
        previous = [
            {"line_no": "A", "stop_no": "1", "eventDate": "2026-03-16 09:00:00"},
            {"line_no": "A", "stop_no": "1", "eventDate": "2026-03-16 09:05:00"},
        ]
        row = hssc.HsscRow("A", "ENTERED", "1", "5", "성균관대입구사거리",
                           "2026-03-16 오전 9:09:00")
        got = hssc.normalize(previous, [row], now=datetime(2026, 3, 16, 9, 9, tzinfo=KST))
        assert got[0]["eventDate"] == "2026-03-16 09:00:00"
        assert got[0]["estimatedTime"] == 540

    @pytest.mark.parametrize("bad_seq", ["", "5abc", "5.9", "١٢"])
    def test_a_non_integer_seq_is_refused_at_parse_with_this_modules_error(self, bad_seq):
        """It used to escape normalize() as a bare ValueError, which is not
        the type parse() advertises and which took the whole tick with it.
        Refusing is right; refusing where the message can name the item is
        better. (The TS publishes the literal string "NaN" here — matching
        that would be reproducing a bug, not a contract.)"""
        item = {
            "line_no": "1", "inout": "x", "stop_no": "2", "seq": bad_seq,
            "stop_name": "성균관대입구사거리", "get_date": "2026-03-16 오전 8:00:00",
        }
        with pytest.raises(hssc.HsscPayloadError, match="seq"):
            hssc.parse([item])

    @pytest.mark.parametrize("padded", ["07", " 5"])
    def test_the_integer_shapes_parseInt_accepts_still_work(self, padded):
        item = {
            "line_no": "1", "inout": "x", "stop_no": "2", "seq": padded,
            "stop_name": "성균관대입구사거리", "get_date": "2026-03-16 오전 8:00:00",
        }
        assert hssc.parse([item]) is not None

    @pytest.mark.parametrize(
        "impossible",
        [
            "2026-13-45 오전 8:00:00",
            "2026-02-30 오전 8:00:00",
            "2026-03-16 오전 8:99:99",
        ],
    )
    def test_an_impossible_date_raises_this_modules_error_not_a_bare_one(self, impossible):
        """The regex validates shape, not the calendar. datetime() catches
        these but as a bare ValueError naming neither field nor input, so a
        caller following the documented `except KoreanTimeFormatError`
        contract would miss them."""
        with pytest.raises(KoreanTimeFormatError, match="not a real instant"):
            parse_korean(impossible)

    def test_the_station_order_invariants_are_validated(self):
        """`sequence` is derived from array position, so a reordered file
        renders every bus against the wrong station name with nothing
        raising. skkuverse-server refuses to boot on the same bytes."""
        stations = [
            {"stationName": "A", "arsId": "1", "topisId": "T1", "isFirstStation": True},
            {"stationName": "B", "arsId": "2", "topisId": "T2", "isLastStation": True},
        ]
        route = {
            "id": "jongro02", "busRouteId": "1", "themeColor": "abcdef",
            "iconType": "bus", "refreshInterval": 40, "stations": stations,
        }
        assert validate_routes([route]) == []

        errors = validate_routes([dict(route, stations=list(reversed(stations)))])
        assert any("isFirstStation" in e for e in errors)

    def test_the_shipped_routes_satisfy_those_invariants(self):
        """Guards the guard: an invariant the shipped file already violates
        would make every load raise, so this pins that it does not."""
        import json as _json
        from importlib import resources as _resources

        raw = _json.loads(
            _resources.files("skkuverse_crawler.modules.bus")
            .joinpath("jongro-routes.json")
            .read_text(encoding="utf-8")
        )
        assert validate_routes(raw) == []
