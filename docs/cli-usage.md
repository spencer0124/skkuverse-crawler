# CLI Usage

## Commands

```bash
cd py

# 1회 incremental 크롤링 (새 글만)
python -m skkuverse_crawler notices --once

# 1회 전체 크롤링 (incremental 무시)
python -m skkuverse_crawler notices --once --all

# 특정 학과만, 지정 페이지 수
python -m skkuverse_crawler notices --once --dept skku-main --pages 3

# 요청 간 딜레이 변경 (기본 500ms)
python -m skkuverse_crawler notices --once --delay 1000

# 스케줄러
python -m skkuverse_crawler start

# 단일 모듈만 스케줄링
python -m skkuverse_crawler start --module notices
```

## Options

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--once` | false | 1회 실행 후 종료 (없으면 cron 모드) |
| `--all` | false | incremental 무시, 모든 페이지 크롤링 |
| `--dept <id>` | 전체 | 특정 학과만 크롤링 (departments.json의 id) |
| `--pages <n>` | 무제한 | 최대 페이지 수 제한 |
| `--delay <ms>` | 500 | 요청 간 최소 딜레이 (밀리초) |

## 소요시간 추정 (500ms 딜레이 기준)

| 시나리오 | 요청 수 | 소요시간 |
|----------|---------|----------|
| 평상시 incremental (새 글 0~5건) | 1~6 | ~3초 |
| --pages 3 (30건 목록+상세) | 33 | ~17초 |
| 초기 풀 크롤링 50페이지 (500건) | 550 | ~5분 |
