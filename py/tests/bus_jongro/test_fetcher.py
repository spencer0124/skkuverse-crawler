from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from skkuverse_crawler.bus_jongro import fetcher
from skkuverse_crawler.bus_jongro.fetcher import update_jongro_buses

JONGRO_LIST_RESPONSE = {
    "msgBody": {
        "itemList": [
            {
                "stId": "100900204",
                "staOrd": "1",
                "stNm": "성균관대학교",
                "plainNo1": "서울74사5512",
                "mkTm": "2026-04-05 14:30:00.0",
                "arsId": "01881",
                "arrmsg1": "3분후[1번째 전]",
            },
            {
                "stId": "100900202",
                "staOrd": "2",
                "stNm": "서울성곽.성대후문",
                "plainNo1": "",
                "mkTm": "2026-04-05 14:30:00.0",
                "arsId": "01515",
                "arrmsg1": "출발대기",
            },
        ]
    }
}

JONGRO_LOC_RESPONSE = {
    "msgBody": {
        "itemList": [
            {
                "lastStnId": "100900204",
                "tmX": "126.990142",
                "tmY": "37.588643",
                "plainNo": "서울74사5512",
            },
        ]
    }
}

EMPTY_RESPONSE = {"msgBody": {}}


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    monkeypatch.setenv("API_JONGRO02_LIST_URL", "http://test/j02-list")
    monkeypatch.setenv("API_JONGRO07_LIST_URL", "http://test/j07-list")
    monkeypatch.setenv("API_JONGRO02_LOC_URL", "http://test/j02-loc")
    monkeypatch.setenv("API_JONGRO07_LOC_URL", "http://test/j07-loc")


@pytest.fixture(autouse=True)
def _reset_state():
    fetcher._bus_station_times.clear()
    yield
    fetcher._bus_station_times.clear()


class TestUpdateJongroBuses:
    @respx.mock
    async def test_successful_fetch_all_four_apis(self, _mock_db):
        respx.get("http://test/j02-list").mock(
            return_value=httpx.Response(200, json=JONGRO_LIST_RESPONSE)
        )
        respx.get("http://test/j07-list").mock(
            return_value=httpx.Response(200, json=JONGRO_LIST_RESPONSE)
        )
        respx.get("http://test/j02-loc").mock(
            return_value=httpx.Response(200, json=JONGRO_LOC_RESPONSE)
        )
        respx.get("http://test/j07-loc").mock(
            return_value=httpx.Response(200, json=EMPTY_RESPONSE)
        )

        with patch("skkuverse_crawler.shared.bus_cache.write", new_callable=AsyncMock) as mock_write:
            result = await update_jongro_buses()

        assert result["status"] == "ok"
        assert len(result["results"]) == 4

        write_keys = [call[0][0] for call in mock_write.call_args_list]
        assert "jongro_stations_02" in write_keys
        assert "jongro_stations_07" in write_keys
        assert "jongro_locations_02" in write_keys

    @respx.mock
    async def test_list_api_transforms_data_correctly(self, _mock_db):
        respx.get("http://test/j02-list").mock(
            return_value=httpx.Response(200, json=JONGRO_LIST_RESPONSE)
        )
        respx.get("http://test/j07-list").mock(
            return_value=httpx.Response(200, json=EMPTY_RESPONSE)
        )
        respx.get("http://test/j02-loc").mock(
            return_value=httpx.Response(200, json=EMPTY_RESPONSE)
        )
        respx.get("http://test/j07-loc").mock(
            return_value=httpx.Response(200, json=EMPTY_RESPONSE)
        )

        with patch("skkuverse_crawler.shared.bus_cache.write", new_callable=AsyncMock) as mock_write:
            await update_jongro_buses()

        # Find the jongro_stations_02 write
        for call in mock_write.call_args_list:
            if call[0][0] == "jongro_stations_02":
                stations = call[0][1]
                assert len(stations) == 2
                assert stations[0]["stationId"] == "100900204"
                assert stations[0]["stationName"] == "성균관대학교"
                assert stations[0]["carNumber"] == "5512"
                assert stations[0]["eta"] == "3분후[1번째 전]"
                # Empty plainNo1 → "----"
                assert stations[1]["carNumber"] == "----"
                break
        else:
            pytest.fail("jongro_stations_02 write not found")

    @respx.mock
    async def test_location_api_maps_station_and_extracts_car_number(self, _mock_db):
        respx.get("http://test/j02-list").mock(
            return_value=httpx.Response(200, json=EMPTY_RESPONSE)
        )
        respx.get("http://test/j07-list").mock(
            return_value=httpx.Response(200, json=EMPTY_RESPONSE)
        )
        respx.get("http://test/j02-loc").mock(
            return_value=httpx.Response(200, json=JONGRO_LOC_RESPONSE)
        )
        respx.get("http://test/j07-loc").mock(
            return_value=httpx.Response(200, json=EMPTY_RESPONSE)
        )

        with patch("skkuverse_crawler.shared.bus_cache.write", new_callable=AsyncMock) as mock_write:
            await update_jongro_buses()

        for call in mock_write.call_args_list:
            if call[0][0] == "jongro_locations_02":
                locations = call[0][1]
                assert len(locations) == 1
                loc = locations[0]
                assert loc["stationName"] == "성균관대학교"
                assert loc["sequence"] == "1"
                assert loc["carNumber"] == "5512"
                assert loc["latitude"] == "37.588643"
                assert loc["longitude"] == "126.990142"
                assert loc["estimatedTime"] == 0  # first observation
                break
        else:
            pytest.fail("jongro_locations_02 write not found")

    @respx.mock
    async def test_location_unmapped_station_skipped(self, _mock_db):
        unmapped_response = {
            "msgBody": {
                "itemList": [
                    {
                        "lastStnId": "999999999",  # not in mapping
                        "tmX": "126.0",
                        "tmY": "37.0",
                        "plainNo": "1234",
                    },
                ]
            }
        }

        respx.get("http://test/j02-list").mock(return_value=httpx.Response(200, json=EMPTY_RESPONSE))
        respx.get("http://test/j07-list").mock(return_value=httpx.Response(200, json=EMPTY_RESPONSE))
        respx.get("http://test/j02-loc").mock(return_value=httpx.Response(200, json=unmapped_response))
        respx.get("http://test/j07-loc").mock(return_value=httpx.Response(200, json=EMPTY_RESPONSE))

        with patch("skkuverse_crawler.shared.bus_cache.write", new_callable=AsyncMock) as mock_write:
            await update_jongro_buses()

        for call in mock_write.call_args_list:
            if call[0][0] == "jongro_locations_02":
                assert call[0][1] == []
                break

    @respx.mock
    async def test_one_api_failure_doesnt_block_others(self, _mock_db):
        respx.get("http://test/j02-list").mock(return_value=httpx.Response(500))
        respx.get("http://test/j07-list").mock(
            return_value=httpx.Response(200, json=JONGRO_LIST_RESPONSE)
        )
        respx.get("http://test/j02-loc").mock(return_value=httpx.Response(500))
        respx.get("http://test/j07-loc").mock(
            return_value=httpx.Response(200, json=EMPTY_RESPONSE)
        )

        with patch("skkuverse_crawler.shared.bus_cache.write", new_callable=AsyncMock) as mock_write:
            result = await update_jongro_buses()

        assert result["status"] == "ok"
        errors = [r for r in result["results"] if r["status"] == "error"]
        successes = [r for r in result["results"] if r["status"] != "error"]
        assert len(errors) == 2
        assert len(successes) >= 1

    async def test_missing_env_vars_returns_skipped(self, monkeypatch, _mock_db):
        monkeypatch.delenv("API_JONGRO02_LIST_URL", raising=False)
        monkeypatch.delenv("API_JONGRO07_LIST_URL", raising=False)

        result = await update_jongro_buses()
        assert result["status"] == "skipped"
        assert "API_JONGRO02_LIST_URL" in result["missing"]


class TestModuleConfig:
    def test_bus_hssc_config(self):
        from skkuverse_crawler.bus_hssc.module import BusHsscModule

        mod = BusHsscModule()
        assert mod.config.name == "bus-hssc"
        assert mod.config.collection_name == "bus_cache"
        assert mod.config.interval_seconds == 10
        assert mod.config.cron_schedule is None

    def test_bus_jongro_config(self):
        from skkuverse_crawler.bus_jongro.module import BusJongroModule

        mod = BusJongroModule()
        assert mod.config.name == "bus-jongro"
        assert mod.config.collection_name == "bus_cache"
        assert mod.config.interval_seconds == 40
        assert mod.config.cron_schedule is None

    def test_notices_config_still_works(self):
        from skkuverse_crawler.notices.module import NoticesModule

        mod = NoticesModule()
        assert mod.config.name == "notices"
        assert mod.config.cron_schedule == "*/30 * * * *"
        assert mod.config.interval_seconds is None
