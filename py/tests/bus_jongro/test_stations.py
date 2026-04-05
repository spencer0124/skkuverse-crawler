from __future__ import annotations

from skkuverse_crawler.bus_jongro.stations import (
    JONGRO_02_STATIONS,
    JONGRO_02_STATION_MAPPING,
    JONGRO_07_STATIONS,
    JONGRO_07_STATION_MAPPING,
    STATION_MAPPINGS,
)


def test_jongro_02_station_count():
    assert len(JONGRO_02_STATIONS) == 26


def test_jongro_07_station_count():
    assert len(JONGRO_07_STATIONS) == 19


def test_jongro_02_mapping_count():
    assert len(JONGRO_02_STATION_MAPPING) == 26


def test_jongro_07_mapping_count():
    assert len(JONGRO_07_STATION_MAPPING) == 19


def test_station_mappings_has_both_routes():
    assert "02" in STATION_MAPPINGS
    assert "07" in STATION_MAPPINGS


def test_jongro_02_first_station():
    assert JONGRO_02_STATIONS[0]["stationName"] == "성균관대학교"
    assert JONGRO_02_STATIONS[0]["stationNumber"] == "01881"


def test_jongro_07_last_station():
    assert JONGRO_07_STATIONS[-1]["stationName"] == "성균관대학교"
    assert JONGRO_07_STATIONS[-1]["stationNumber"] == "01722"


def test_mapping_sequences_are_contiguous():
    """Station mapping sequences should cover 1..N without gaps."""
    for name, mapping in [("02", JONGRO_02_STATION_MAPPING), ("07", JONGRO_07_STATION_MAPPING)]:
        seqs = sorted(v["sequence"] for v in mapping.values())
        assert seqs == list(range(1, len(mapping) + 1)), f"Route {name} has non-contiguous sequences"


def test_mapping_station_ids_are_strings():
    """All station IDs in mappings should be string keys."""
    for mapping in [JONGRO_02_STATION_MAPPING, JONGRO_07_STATION_MAPPING]:
        for key in mapping:
            assert isinstance(key, str)
