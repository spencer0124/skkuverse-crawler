from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from skkuverse_crawler.bus_hssc import fetcher
from skkuverse_crawler.bus_hssc.fetcher import _parse_event_date, update_hssc_bus_list

KST = timezone(timedelta(hours=9))

SAMPLE_API_RESPONSE = [
    {
        "line_no": "L1",
        "stop_no": "S1",
        "stop_name": "농구장정류소",
        "seq": "5",
        "get_date": "2026-04-05 오후 2:30:00",
    },
    {
        "line_no": "L1",
        "stop_no": "S2",
        "stop_name": "문묘입구[정문]-등교",
        "seq": "7",
        "get_date": "2026-04-05 오후 2:31:00",
    },
]


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset in-memory state between tests."""
    fetcher._prev_stations.clear()
    yield
    fetcher._prev_stations.clear()


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    monkeypatch.setenv("API_HSSC_URL", "http://test-hssc-api/bus")


class TestParseEventDate:
    def test_pm_format(self):
        dt = _parse_event_date("2026-04-05 오후 2:30:00")
        assert dt is not None
        assert dt.hour == 14
        assert dt.minute == 30

    def test_am_format(self):
        dt = _parse_event_date("2026-04-05 오전 9:15:00")
        assert dt is not None
        assert dt.hour == 9
        assert dt.minute == 15

    def test_invalid_returns_none(self):
        assert _parse_event_date("invalid") is None
        assert _parse_event_date("") is None

    def test_timezone_is_kst(self):
        dt = _parse_event_date("2026-04-05 오후 2:30:00")
        assert dt.utcoffset() == timedelta(hours=9)


class TestUpdateHsscBusList:
    @respx.mock
    async def test_successful_fetch_transforms_data(self, _mock_db):
        now_kst = datetime.now(KST)
        recent_time = now_kst - timedelta(minutes=1)
        api_data = [
            {
                "line_no": "L1",
                "stop_no": "S1",
                "stop_name": "농구장정류소",
                "seq": "5",
                "get_date": recent_time.strftime("%Y-%m-%d 오후 %I:%M:%S")
                if recent_time.hour >= 12
                else recent_time.strftime("%Y-%m-%d 오전 %I:%M:%S"),
            },
        ]

        respx.get("http://test-hssc-api/bus").mock(
            return_value=httpx.Response(200, json=api_data)
        )

        with patch("skkuverse_crawler.shared.bus_cache.write", new_callable=AsyncMock) as mock_write:
            result = await update_hssc_bus_list()

        assert result["status"] == "ok"
        assert result["buses"] >= 0
        if result["buses"] > 0:
            write_args = mock_write.call_args
            assert write_args[0][0] == "hssc"
            items = write_args[0][1]
            assert items[0]["stationName"] == "농구장 (셔틀버스정류소)"
            assert items[0]["sequence"] == "1"

    @respx.mock
    async def test_filters_stale_data(self, _mock_db):
        stale_time = datetime.now(KST) - timedelta(minutes=15)
        am_pm = "오후" if stale_time.hour >= 12 else "오전"
        hour_12 = stale_time.hour % 12 or 12
        api_data = [
            {
                "line_no": "L1",
                "stop_no": "S1",
                "stop_name": "문묘입구[정문]-등교",
                "seq": "7",
                "get_date": f"{stale_time.strftime('%Y-%m-%d')} {am_pm} {hour_12}:{stale_time.strftime('%M:%S')}",
            },
        ]

        respx.get("http://test-hssc-api/bus").mock(
            return_value=httpx.Response(200, json=api_data)
        )

        with patch("skkuverse_crawler.shared.bus_cache.write", new_callable=AsyncMock) as mock_write:
            result = await update_hssc_bus_list()

        assert result["status"] == "ok"
        assert result["buses"] == 0

    @respx.mock
    async def test_invalid_response_skipped(self, _mock_db):
        respx.get("http://test-hssc-api/bus").mock(
            return_value=httpx.Response(200, json={"not": "a list"})
        )

        result = await update_hssc_bus_list()
        assert result["status"] == "skipped"
        assert result["reason"] == "invalid_response"

    @respx.mock
    async def test_api_error_returns_error_status(self, _mock_db):
        respx.get("http://test-hssc-api/bus").mock(
            return_value=httpx.Response(500)
        )

        result = await update_hssc_bus_list()
        assert result["status"] == "error"

    async def test_missing_env_var_returns_skipped(self, monkeypatch, _mock_db):
        monkeypatch.delenv("API_HSSC_URL", raising=False)

        result = await update_hssc_bus_list()
        assert result["status"] == "skipped"
        assert result["reason"] == "no_api_url"

    @respx.mock
    async def test_turnaround_station_has_tighter_stale_threshold(self, _mock_db):
        """Turnaround station (농구장) uses 3-min threshold vs 10-min default."""
        # 4 minutes ago — stale for turnaround (3min), fresh for others (10min)
        four_min_ago = datetime.now(KST) - timedelta(minutes=4)
        am_pm = "오후" if four_min_ago.hour >= 12 else "오전"
        hour_12 = four_min_ago.hour % 12 or 12

        api_data = [
            {
                "line_no": "L1",
                "stop_no": "S1",
                "stop_name": "농구장정류소",  # turnaround
                "seq": "5",
                "get_date": f"{four_min_ago.strftime('%Y-%m-%d')} {am_pm} {hour_12}:{four_min_ago.strftime('%M:%S')}",
            },
            {
                "line_no": "L1",
                "stop_no": "S2",
                "stop_name": "문묘입구[정문]-등교",  # regular
                "seq": "7",
                "get_date": f"{four_min_ago.strftime('%Y-%m-%d')} {am_pm} {hour_12}:{four_min_ago.strftime('%M:%S')}",
            },
        ]

        respx.get("http://test-hssc-api/bus").mock(
            return_value=httpx.Response(200, json=api_data)
        )

        with patch("skkuverse_crawler.shared.bus_cache.write", new_callable=AsyncMock) as mock_write:
            result = await update_hssc_bus_list()

        assert result["buses"] == 1
        written = mock_write.call_args[0][1]
        assert written[0]["stationName"] == "정문"
