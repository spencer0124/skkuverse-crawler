from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone, timedelta

import httpx

from ..shared import bus_cache
from ..shared.logger import get_logger
from .stations import STATION_MAPPINGS, STALE_MINUTES

logger = get_logger("bus_jongro")

# In-memory ETA tracking: {busnumber: {stationId: iso_timestamp}}
_bus_station_times: dict[str, dict[str, str]] = {}


async def _update_bus_list(
    client: httpx.AsyncClient, url: str, busnumber: str,
) -> dict:
    """Fetch bus arrival list for a Jongro route and write to bus_cache."""
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        api_data = resp.json().get("msgBody", {}).get("itemList")
        if not api_data:
            return {"key": f"jongro_stations_{busnumber}", "status": "no_data"}

        stations = []
        for item in api_data:
            stations.append({
                "stationId": item.get("stId", ""),
                "sequence": item.get("staOrd", ""),
                "stationName": item.get("stNm", ""),
                "carNumber": (item.get("plainNo1") or "").strip()[-4:] or "----",
                "eventDate": item.get("mkTm", ""),
                "stationNumber": item.get("arsId", ""),
                "eta": item.get("arrmsg1", ""),
            })

        cache_key = f"jongro_stations_{busnumber}"
        await bus_cache.write(cache_key, stations)
        logger.info("list_updated", bus=busnumber, stations=len(stations))
        return {"key": cache_key, "status": "ok", "count": len(stations)}

    except Exception:
        logger.exception("list_update_failed", bus=busnumber)
        return {"key": f"jongro_stations_{busnumber}", "status": "error"}


async def _update_bus_location(
    client: httpx.AsyncClient, url: str, busnumber: str,
) -> dict:
    """Fetch bus GPS locations for a Jongro route and write to bus_cache."""
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        api_data = resp.json().get("msgBody", {}).get("itemList")
        if not api_data:
            return {"key": f"jongro_locations_{busnumber}", "status": "no_data"}

        mapping = STATION_MAPPINGS.get(busnumber, {})
        current_time = datetime.now(timezone.utc)

        if busnumber not in _bus_station_times:
            _bus_station_times[busnumber] = {}
        times = _bus_station_times[busnumber]

        locations = []
        for item in api_data:
            last_stn_id = str(item.get("lastStnId", ""))
            station_info = mapping.get(last_stn_id)
            if not station_info:
                logger.debug("unmapped_station", station_id=last_stn_id, bus=busnumber)
                continue

            # Clean stale tracking records (>10 min)
            if last_stn_id in times:
                last_time = datetime.fromisoformat(times[last_stn_id])
                if (current_time - last_time).total_seconds() / 60 > STALE_MINUTES:
                    del times[last_stn_id]

            # Calculate estimated time
            estimated_time = 0
            if last_stn_id in times:
                last_time = datetime.fromisoformat(times[last_stn_id])
                estimated_time = round((current_time - last_time).total_seconds())
            else:
                times[last_stn_id] = current_time.isoformat()

            plain_no = (item.get("plainNo") or "").strip()
            locations.append({
                "sequence": str(station_info["sequence"]),
                "stationName": station_info["stationName"],
                "carNumber": plain_no[-4:] if len(plain_no) >= 4 else "----",
                "eventDate": times[last_stn_id],
                "estimatedTime": estimated_time,
                "stationId": last_stn_id,
                "latitude": item.get("tmY"),
                "longitude": item.get("tmX"),
                "recordTime": times[last_stn_id],
            })

        cache_key = f"jongro_locations_{busnumber}"
        await bus_cache.write(cache_key, locations)
        logger.info("location_updated", bus=busnumber, buses=len(locations))
        return {"key": cache_key, "status": "ok", "count": len(locations)}

    except Exception:
        logger.exception("location_update_failed", bus=busnumber)
        return {"key": f"jongro_locations_{busnumber}", "status": "error"}


async def update_jongro_buses() -> dict:
    """Poll all 4 Jongro bus APIs in parallel."""
    list_02_url = os.getenv("API_JONGRO02_LIST_URL")
    list_07_url = os.getenv("API_JONGRO07_LIST_URL")
    loc_02_url = os.getenv("API_JONGRO02_LOC_URL")
    loc_07_url = os.getenv("API_JONGRO07_LOC_URL")

    urls = {
        "API_JONGRO02_LIST_URL": list_02_url,
        "API_JONGRO07_LIST_URL": list_07_url,
        "API_JONGRO02_LOC_URL": loc_02_url,
        "API_JONGRO07_LOC_URL": loc_07_url,
    }
    missing = [k for k, v in urls.items() if not v]
    if missing:
        logger.warning("api_urls_not_configured", vars=missing)
        return {"status": "skipped", "reason": "missing_urls", "missing": missing}

    await bus_cache.ensure_index()

    async with httpx.AsyncClient(timeout=10.0) as client:
        results = await asyncio.gather(
            _update_bus_list(client, list_02_url, "02"),
            _update_bus_list(client, list_07_url, "07"),
            _update_bus_location(client, loc_02_url, "02"),
            _update_bus_location(client, loc_07_url, "07"),
            return_exceptions=True,
        )

    summary: dict = {"status": "ok", "results": []}
    for r in results:
        if isinstance(r, Exception):
            logger.exception("unexpected_error", error=str(r))
            summary["results"].append({"status": "error", "error": str(r)})
        else:
            summary["results"].append(r)

    return summary
