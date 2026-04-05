from __future__ import annotations

from skkuverse_crawler.bus_hssc.fetcher import _to_linear_sequence
from skkuverse_crawler.bus_hssc.stations import HSSC_STATIONS, STOP_NAME_MAPPING


def test_to_linear_sequence_high():
    """seq >= 5 maps to seq - 4 (5->1, 6->2, ..., 10->6)."""
    assert _to_linear_sequence(5) == 1
    assert _to_linear_sequence(6) == 2
    assert _to_linear_sequence(7) == 3
    assert _to_linear_sequence(8) == 4
    assert _to_linear_sequence(9) == 5
    assert _to_linear_sequence(10) == 6


def test_to_linear_sequence_low():
    """seq < 5 maps to seq + 7 (0->7, 1->8, ..., 4->11)."""
    assert _to_linear_sequence(0) == 7
    assert _to_linear_sequence(1) == 8
    assert _to_linear_sequence(2) == 9
    assert _to_linear_sequence(3) == 10
    assert _to_linear_sequence(4) == 11


def test_to_linear_sequence_covers_full_range():
    """All 11 circular positions (0-10) map to unique linear positions (1-11)."""
    results = [_to_linear_sequence(i) for i in range(11)]
    assert sorted(results) == list(range(1, 12))


def test_hssc_stations_count():
    assert len(HSSC_STATIONS) == 11


def test_hssc_stations_sequences():
    sequences = [s["sequence"] for s in HSSC_STATIONS]
    assert sequences == list(range(1, 12))


def test_stop_name_mapping_has_all_entries():
    assert len(STOP_NAME_MAPPING) == 10
    assert STOP_NAME_MAPPING["농구장정류소"] == "농구장 (셔틀버스정류소)"
    assert STOP_NAME_MAPPING["600주년기념관 앞-등교"] == "600주년기념관"
    assert STOP_NAME_MAPPING["문묘입구[정문]-등교"] == "정문"
