from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

import httpx

from ..shared import bus_cache
from ..shared.logger import get_logger
from .stations import (
    STOP_NAME_MAPPING,
    STALE_MINUTES_DEFAULT,
    STALE_MINUTES_TURNAROUND,
    TURNAROUND_STATION,
)

logger = get_logger("bus_hssc")

# In-memory state: tracks previous eventDate per (line_no, stop_no)
_prev_stations: dict[tuple[str, str], datetime] = {}


def _to_linear_sequence(seq: int) -> int:
    """Convert circular route index (0-10) to linear station sequence (1-11)."""
    return seq - 4 if seq >= 5 else seq + 7


def _parse_event_date(raw: str) -> datetime | None:
    """Parse HSSC API date format: 'YYYY-MM-DD 오전/오후 h:mm:ss'."""
    try:
        # Replace Korean AM/PM markers
        normalized = raw.replace("오전", "AM").replace("오후", "PM")
        return datetime.strptime(normalized, "%Y-%m-%d %p %I:%M:%S").replace(
            tzinfo=timezone(timedelta(hours=9))
        )
    except (ValueError, AttributeError):
        return None


async def update_hssc_bus_list() -> dict:
    """Fetch HSSC shuttle bus positions and write to bus_cache."""
    api_url = os.getenv("API_HSSC_URL")
    if not api_url:
        logger.warning("api_url_not_configured", var="API_HSSC_URL")
        return {"status": "skipped", "reason": "no_api_url"}

    await bus_cache.ensure_index()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(api_url)
            resp.raise_for_status()
            api_data = resp.json()

        if not isinstance(api_data, list):
            return {"status": "skipped", "reason": "invalid_response"}

        now = datetime.now(timezone(timedelta(hours=9)))
        updated: list[dict] = []

        for item in api_data:
            line_no = item.get("line_no", "")
            stop_no = item.get("stop_no", "")
            key = (line_no, stop_no)

            # Use previous eventDate if available, otherwise parse from API
            if key in _prev_stations:
                event_dt = _prev_stations[key]
            else:
                event_dt = _parse_event_date(item.get("get_date", ""))
                if event_dt is None:
                    continue

            seq = int(item.get("seq", 0))
            real_sequence = _to_linear_sequence(seq)
            station_name = STOP_NAME_MAPPING.get(item.get("stop_name", ""), item.get("stop_name", ""))
            time_diff = abs((now - event_dt).total_seconds())

            entry = {
                "sequence": str(real_sequence),
                "stationName": station_name,
                "carNumber": "0000",
                "eventDate": event_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "estimatedTime": round(time_diff),
                "isLastBus": False,
                "line_no": line_no,
                "stop_no": stop_no,
                "get_date": item.get("get_date", ""),
            }

            # Stale filtering
            stale_minutes = (
                STALE_MINUTES_TURNAROUND
                if station_name == TURNAROUND_STATION
                else STALE_MINUTES_DEFAULT
            )
            cutoff = now - timedelta(minutes=stale_minutes)
            if event_dt < cutoff:
                _prev_stations.pop(key, None)
                continue

            _prev_stations[key] = event_dt
            updated.append(entry)

        await bus_cache.write("hssc", updated)
        logger.info("poll_complete", buses=len(updated))
        return {"status": "ok", "buses": len(updated)}

    except Exception:
        logger.exception("poll_failed")
        return {"status": "error"}
