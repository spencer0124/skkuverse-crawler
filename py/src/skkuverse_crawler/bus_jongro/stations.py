from __future__ import annotations

STALE_MINUTES = 10

# --- Jongro 02 (26 stations, round-trip SKKU - Jongno) ---

JONGRO_02_STATIONS: list[dict] = [
    {"sequence": "1", "stationName": "성균관대학교", "stationNumber": "01881"},
    {"sequence": "2", "stationName": "서울성곽.성대후문", "stationNumber": "01515"},
    {"sequence": "3", "stationName": "통일부", "stationNumber": "01525"},
    {"sequence": "4", "stationName": "감사원", "stationNumber": "01536"},
    {"sequence": "5", "stationName": "사우디대사관앞.경남빌라", "stationNumber": "01547"},
    {"sequence": "6", "stationName": "안국선원.삼거리", "stationNumber": "01548"},
    {"sequence": "7", "stationName": "북촌한옥마을입구.정세권활동터", "stationNumber": "01556"},
    {"sequence": "8", "stationName": "가회동주민센터", "stationNumber": "01564"},
    {"sequence": "9", "stationName": "아름다운가게.정독도서관", "stationNumber": "01570"},
    {"sequence": "10", "stationName": "헌법재판소.안국역", "stationNumber": "01576"},
    {"sequence": "11", "stationName": "수운회관", "stationNumber": "01583"},
    {"sequence": "12", "stationName": "낙원상가", "stationNumber": "01589"},
    {"sequence": "13", "stationName": "금강제화", "stationNumber": "01596"},
    {"sequence": "14", "stationName": "종각역YMCA", "stationNumber": "01683"},
    {"sequence": "15", "stationName": "종각.공평유적전시관", "stationNumber": "01888"},
    {"sequence": "16", "stationName": "조계사", "stationNumber": "01889"},
    {"sequence": "17", "stationName": "안국역.인사동", "stationNumber": "01200"},
    {"sequence": "18", "stationName": "안국역2번출구앞", "stationNumber": "01805"},
    {"sequence": "19", "stationName": "재동초등학교", "stationNumber": "01812"},
    {"sequence": "20", "stationName": "가회동주민센터", "stationNumber": "01826"},
    {"sequence": "21", "stationName": "북촌한옥마을입구.정세권활동터", "stationNumber": "01833"},
    {"sequence": "22", "stationName": "안국선원.삼거리", "stationNumber": "01839"},
    {"sequence": "23", "stationName": "사우디대사관", "stationNumber": "01845"},
    {"sequence": "24", "stationName": "감사원", "stationNumber": "01851"},
    {"sequence": "25", "stationName": "통일부", "stationNumber": "01856"},
    {"sequence": "26", "stationName": "성대후문.와룡공원", "stationNumber": "01860"},
]

JONGRO_02_STATION_MAPPING: dict[str, dict] = {
    "100900204": {"sequence": 1, "stationName": "성균관대학교"},
    "100900202": {"sequence": 2, "stationName": "서울성곽.성대후문"},
    "100900045": {"sequence": 3, "stationName": "통일부"},
    "100900069": {"sequence": 4, "stationName": "감사원"},
    "100900059": {"sequence": 5, "stationName": "사우디대사관앞.경남빌라"},
    "100900058": {"sequence": 6, "stationName": "안국선원.삼거리"},
    "100900052": {"sequence": 7, "stationName": "북촌한옥마을입구.정세권활동터"},
    "100900048": {"sequence": 8, "stationName": "가회동주민센터"},
    "100900092": {"sequence": 9, "stationName": "아름다운가게.정독도서관"},
    "100900086": {"sequence": 10, "stationName": "헌법재판소.안국역"},
    "100900081": {"sequence": 11, "stationName": "수운회관"},
    "100900078": {"sequence": 12, "stationName": "낙원상가"},
    "100900121": {"sequence": 13, "stationName": "금강제화"},
    "100900116": {"sequence": 14, "stationName": "종각역YMCA"},
    "100900211": {"sequence": 15, "stationName": "종각.공평유적전시관"},
    "100900213": {"sequence": 16, "stationName": "조계사"},
    "100000104": {"sequence": 17, "stationName": "안국역.인사동"},
    "100900189": {"sequence": 18, "stationName": "안국역2번출구앞"},
    "100900131": {"sequence": 19, "stationName": "재동초등학교"},
    "100900168": {"sequence": 20, "stationName": "가회동주민센터"},
    "100900162": {"sequence": 21, "stationName": "북촌한옥마을입구.정세권활동터"},
    "100900157": {"sequence": 22, "stationName": "안국선원.삼거리"},
    "100900153": {"sequence": 23, "stationName": "사우디대사관"},
    "100900147": {"sequence": 24, "stationName": "감사원"},
    "100900172": {"sequence": 25, "stationName": "통일부"},
    "100900203": {"sequence": 26, "stationName": "성대후문.와룡공원"},
}

# --- Jongro 07 (19 stations) ---

JONGRO_07_STATIONS: list[dict] = [
    {"sequence": "1", "stationName": "명륜새마을금고", "stationNumber": "01504"},
    {"sequence": "2", "stationName": "서울국제고등학교", "stationNumber": "01512"},
    {"sequence": "3", "stationName": "국민생활관", "stationNumber": "01521"},
    {"sequence": "4", "stationName": "혜화초등학교", "stationNumber": "01532"},
    {"sequence": "5", "stationName": "혜화우체국", "stationNumber": "01543"},
    {"sequence": "6", "stationName": "혜화역4번출구", "stationNumber": "01876"},
    {"sequence": "7", "stationName": "혜화역.서울대병원입구", "stationNumber": "01221"},
    {"sequence": "8", "stationName": "방송통신대앞", "stationNumber": "01877"},
    {"sequence": "9", "stationName": "이화사거리", "stationNumber": "01886"},
    {"sequence": "10", "stationName": "방송통신대.이화장", "stationNumber": "01219"},
    {"sequence": "11", "stationName": "혜화역.마로니에공원", "stationNumber": "01220"},
    {"sequence": "12", "stationName": "혜화역1번출구", "stationNumber": "01592"},
    {"sequence": "13", "stationName": "혜화동로터리", "stationNumber": "01226"},
    {"sequence": "14", "stationName": "성대입구", "stationNumber": "01697"},
    {"sequence": "15", "stationName": "성균관대정문", "stationNumber": "01615"},
    {"sequence": "16", "stationName": "600주년기념관", "stationNumber": "01616"},
    {"sequence": "17", "stationName": "성균관대운동장", "stationNumber": "01617"},
    {"sequence": "18", "stationName": "학생회관", "stationNumber": "01618"},
    {"sequence": "19", "stationName": "성균관대학교", "stationNumber": "01722"},
]

JONGRO_07_STATION_MAPPING: dict[str, dict] = {
    "100900197": {"sequence": 1, "stationName": "명륜새마을금고"},
    "100900031": {"sequence": 2, "stationName": "서울국제고등학교"},
    "100900017": {"sequence": 3, "stationName": "국민생활관"},
    "100900003": {"sequence": 4, "stationName": "혜화초등학교"},
    "100900063": {"sequence": 5, "stationName": "혜화우체국"},
    "100900027": {"sequence": 6, "stationName": "혜화역4번출구"},
    "100000125": {"sequence": 7, "stationName": "혜화역.서울대병원입구"},
    "100900028": {"sequence": 8, "stationName": "방송통신대앞"},
    "100900043": {"sequence": 9, "stationName": "이화사거리"},
    "100000123": {"sequence": 10, "stationName": "방송통신대.이화장"},
    "100000124": {"sequence": 11, "stationName": "혜화역.마로니에공원"},
    "100900075": {"sequence": 12, "stationName": "혜화역1번출구"},
    "100000130": {"sequence": 13, "stationName": "혜화동로터리"},
    "100900199": {"sequence": 14, "stationName": "성대입구"},
    "100900218": {"sequence": 15, "stationName": "성균관대정문"},
    "100900219": {"sequence": 16, "stationName": "600주년기념관"},
    "100900220": {"sequence": 17, "stationName": "성균관대운동장"},
    "100900221": {"sequence": 18, "stationName": "학생회관"},
    "100900110": {"sequence": 19, "stationName": "성균관대학교"},
}

STATION_MAPPINGS: dict[str, dict[str, dict]] = {
    "02": JONGRO_02_STATION_MAPPING,
    "07": JONGRO_07_STATION_MAPPING,
}
