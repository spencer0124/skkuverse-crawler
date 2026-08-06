"""Campus ETA — the port with no parity corpus.

`hssc` and `jongro` are proven against a month of captured upstream
responses replayed through the server's own compiled transforms. This one
cannot be: the server never polled Naver Directions, it computed on
demand, so nothing was ever captured.

That makes these tests the only evidence, which is why they go after the
places two implementations of the same arithmetic diverge — rounding at
the half-minute, the hour boundary, and every shape the envelope can
arrive in — rather than confirming the happy path twice.
"""

from __future__ import annotations

import pytest

from skkuverse_crawler.modules.bus.campus_eta import (
    LEGS,
    NAVER_DIRECTIONS_URL,
    SEOUL_CAMPUS,
    SUWON_CAMPUS,
    CampusEtaPayloadError,
    EtaData,
    EtaLeg,
    directions_url,
    format_duration,
    read_leg,
)


def _response(duration: int = 1_800_000, distance: int = 45_000) -> dict:
    return {
        "code": 0,
        "message": "길찾기를 성공하였습니다.",
        "route": {"traoptimal": [{"summary": {"duration": duration, "distance": distance}}]},
    }


class TestFormatDuration:
    @pytest.mark.parametrize(
        "ms,expected",
        [
            (0, "0분"),
            (60_000, "1분"),
            (59 * 60_000, "59분"),
            (60 * 60_000, "1시간"),
            (90 * 60_000, "1시간 30분"),
            (120 * 60_000, "2시간"),
            (121 * 60_000, "2시간 1분"),
        ],
    )
    def test_the_three_branches(self, ms, expected):
        assert format_duration(ms) == expected

    def test_zero_still_carries_a_unit(self):
        """The final branch is `${minutes}분`, not an empty string — the
        app renders this into a chip and a bare number would read as a
        distance."""
        assert format_duration(1_000) == "0분"

    def test_the_half_minute_rounds_the_javascript_way(self):
        """`Math.round(30.5) == 31`; Python's `round(30.5) == 30` (banker's
        rounding). Naver reports whole milliseconds, so exact half-minutes
        are reachable and this is a real disagreement, not a hypothetical.
        """
        assert format_duration(30 * 60_000 + 30_000) == "31분"
        assert format_duration(31 * 60_000 + 30_000) == "32분"

    def test_the_hour_boundary_drops_the_minute_component(self):
        """`minutes == 0` takes the hours-only branch, and rounding is what
        decides whether it does: 60.49 minutes prints "1시간" while 60.51
        prints "1시간 1분"."""
        assert format_duration(3_600_000) == "1시간"
        assert format_duration(3_600_000 + 29_999) == "1시간"
        assert format_duration(3_600_000 + 30_000) == "1시간 1분"


class TestReadLeg:
    def test_a_good_response(self):
        leg = read_leg(_response(duration=1_800_000, distance=45_000))
        assert leg == EtaLeg(duration=1_800_000, duration_text="30분", distance=45_000)

    def test_a_nonzero_code_is_refused_before_the_body_is_read(self):
        """Naver sends a well-formed body alongside an error code. Reading
        the body first would publish a route the API said not to trust."""
        payload = _response()
        payload["code"] = 1
        payload["message"] = "출발지와 도착지가 동일합니다."
        with pytest.raises(CampusEtaPayloadError) as exc:
            read_leg(payload)
        assert "code=1" in str(exc.value)
        assert "동일합니다" in str(exc.value), "the upstream's own message is the useful half"

    @pytest.mark.parametrize(
        "payload",
        [
            {"code": 0},
            {"code": 0, "route": {}},
            {"code": 0, "route": {"traoptimal": []}},
            {"code": 0, "route": {"traoptimal": [{}]}},
            {"code": 0, "route": {"traoptimal": "not a list"}},
        ],
        ids=["no route", "no traoptimal", "empty", "no summary", "wrong type"],
    )
    def test_every_way_the_summary_can_be_missing(self, payload):
        with pytest.raises(CampusEtaPayloadError, match="traoptimal"):
            read_leg(payload)

    def test_a_non_object_response(self):
        with pytest.raises(CampusEtaPayloadError, match="list"):
            read_leg([])

    @pytest.mark.parametrize("value", ["1800000", None, True])
    def test_a_non_numeric_duration_is_named(self, value):
        payload = _response()
        payload["route"]["traoptimal"][0]["summary"]["duration"] = value
        with pytest.raises(CampusEtaPayloadError, match="summary.duration"):
            read_leg(payload)

    def test_a_negative_duration_is_refused(self):
        """Not defensive noise: `format_duration` uses `divmod`, and
        Python's floor-modulo disagrees with JavaScript's remainder for
        negatives. Refusing the input makes the disagreement unreachable
        rather than merely unlikely."""
        payload = _response(duration=-1)
        with pytest.raises(CampusEtaPayloadError, match="negative"):
            read_leg(payload)


class TestEtaData:
    def test_complete_needs_both_directions(self):
        leg = EtaLeg(duration=0, duration_text="0분", distance=0)
        assert EtaData(inja=leg, jain=leg).complete
        assert not EtaData(inja=leg, jain=None).complete
        assert not EtaData(inja=None, jain=None).complete

    def test_fields_are_camel_case_and_keep_nulls(self):
        """The keys are what the app reads; a missing leg is `null`, not an
        absent key, because the client checks for the field."""
        leg = EtaLeg(duration=1_800_000, duration_text="30분", distance=45_000)
        assert EtaData(inja=leg, jain=None).as_fields() == {
            "inja": {"duration": 1_800_000, "durationText": "30분", "distance": 45_000},
            "jain": None,
        }


class TestLegTable:
    def test_the_two_directions_are_opposites(self):
        """One table walked by both the scheduled module and `bus --once`,
        so the two cannot end up fetching different directions."""
        assert LEGS == (
            ("inja", (SEOUL_CAMPUS, SUWON_CAMPUS)),
            ("jain", (SUWON_CAMPUS, SEOUL_CAMPUS)),
        )

    def test_the_url_encodes_both_points(self):
        url = directions_url(SEOUL_CAMPUS, SUWON_CAMPUS)
        assert "start=126.993688%2C37.587308" in url
        assert "goal=126.975532%2C37.292345" in url

    def test_it_targets_the_current_maps_host(self):
        """Not a cosmetic detail, and not interchangeable with the legacy
        one. An Application registered against `maps.apigw.ntruss.com`
        answers `naveropenapi.apigw.ntruss.com` with `errorCode 210 /
        Permission Denied`, which reads like a billing problem rather than
        a wrong URL. The TypeScript this was ported from still has the old
        host, which is why its campus ETA stays broken on a working key.
        """
        assert directions_url(SEOUL_CAMPUS, SUWON_CAMPUS).startswith(
            "https://maps.apigw.ntruss.com/map-direction/v1/driving?"
        )
        assert "naveropenapi" not in NAVER_DIRECTIONS_URL
