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

# Tier-2 변경 감지 (최근 14일, 기본값)
python -m skkuverse_crawler update-check

# 윈도우 및 학과 지정
python -m skkuverse_crawler update-check --days 7 --dept skku-main

# cleanHtml/contentText/cleanMarkdown 재생성 (dry-run)
python -m skkuverse_crawler backfill-content

# 실제 업데이트 (학과/건수 제한 가능)
python -m skkuverse_crawler backfill-content --apply --dept cheme --limit 10

# AI 요약 (기본 batch-size: 50)
python -m skkuverse_crawler summarize

# batch-size/delay 지정
python -m skkuverse_crawler summarize --batch-size 500 --delay 2.0

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
| **update-check** | | |
| `--days <n>` | 14 | 변경 감지 윈도우 (일) |
| `--dept <id>` | 전체 | 특정 학과만 체크 |
| **backfill-content** | | |
| `--apply` | false | 실제 업데이트 (없으면 dry-run) |
| `--dept <id>` | 전체 | 특정 학과만 |
| `--limit <n>` | 무제한 | 최대 문서 수 |
| **summarize** | | |
| `--batch-size <n>` | 50 | 배치당 공지 수 |
| `--delay <sec>` | 1.0 | API 호출 간 딜레이 (초) |

## 소요시간 추정 (500ms 딜레이 기준)

| 시나리오 | 요청 수 | 소요시간 |
|----------|---------|----------|
| 평상시 incremental (새 글 0~5건) | 1~6 | ~3초 |
| --pages 3 (30건 목록+상세) | 33 | ~17초 |
| 초기 풀 크롤링 50페이지 (500건) | 550 | ~5분 |
