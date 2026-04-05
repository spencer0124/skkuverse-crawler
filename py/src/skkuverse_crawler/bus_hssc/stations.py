from __future__ import annotations

# API stop_name → normalized display name
STOP_NAME_MAPPING: dict[str, str] = {
    "혜화역 1번출구 셔틀버스 정류소": "혜화역 1번출구 (셔틀버스정류소)",
    "혜화동로터리": "혜화동로터리 [미정차]",
    "성균관대입구사거리": "성균관대입구사거리",
    "문묘입구[정문]-등교": "정문",
    "600주년기념관 앞-등교": "600주년기념관",
    "농구장정류소": "농구장 (셔틀버스정류소)",
    "문묘입구[정문]-하교": "정문",
    "올림픽기념국민생활관": "올림픽기념국민생활관 [하차전용]",
    "600주년기념관 앞-하교": "600주년기념관",
    "서울혜화동우체국": "혜화동우체국 [하차전용]",
}

TURNAROUND_STATION = "농구장 (셔틀버스정류소)"

# Stale thresholds in minutes
STALE_MINUTES_TURNAROUND = 3
STALE_MINUTES_DEFAULT = 10

# Static station list (11 stations, circular route)
HSSC_STATIONS: list[dict] = [
    {"sequence": 1, "stationName": "농구장", "subtitle": "Basketball Court (Shuttle Bus Stop)"},
    {"sequence": 2, "stationName": "학생회관", "subtitle": "Student Center"},
    {"sequence": 3, "stationName": "정문", "subtitle": "Main Gate of SKKU"},
    {"sequence": 4, "stationName": "올림픽기념국민생활관 [하차전용]", "subtitle": "Olympic Hall [Drop-off Only]"},
    {"sequence": 5, "stationName": "혜화동우체국 [하차전용]", "subtitle": "Hyehwa Postoffice [Drop-off Only]"},
    {"sequence": 6, "stationName": "혜화동로터리 [미정차]", "subtitle": "Hyehwa Rotary [Non-stop]"},
    {"sequence": 7, "stationName": "혜화역 1번출구", "subtitle": "Hyehwa Station (Shuttle Bus Stop)"},
    {"sequence": 8, "stationName": "혜화동로터리 [미정차]", "subtitle": "Hyehwa Rotary [Non-stop]"},
    {"sequence": 9, "stationName": "성균관대입구사거리", "subtitle": "SKKU Junction"},
    {"sequence": 10, "stationName": "정문", "subtitle": "Main Gate of SKKU"},
    {"sequence": 11, "stationName": "600주년기념관", "subtitle": "600th Anniversary Hall"},
]
