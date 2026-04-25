# CLI Usage

## Commands

```bash
cd py

# 1회 incremental 크롤링 (새 글만)
python -m skkuverse_crawler notices --once

# 1회 전체 크롤링 (incremental 무시)
python -m skkuverse_crawler notices --once --all

# 특정 학과만, 지정 페이지 수
python -m skkuverse_crawler notices --once --source skku-main --pages 3

# 요청 간 딜레이 변경 (기본 500ms)
python -m skkuverse_crawler notices --once --delay 1000

# Tier-2 변경 감지 (최근 14일, 기본값)
python -m skkuverse_crawler update-check

# 윈도우 및 학과 지정
python -m skkuverse_crawler update-check --days 7 --source skku-main

# cleanHtml/contentText/cleanMarkdown 재생성 (dry-run)
python -m skkuverse_crawler backfill-content

# 실제 업데이트 (학과/건수 제한 가능)
python -m skkuverse_crawler backfill-content --apply --source cheme --limit 10

# AI 요약 (기본 batch-size: 50)
python -m skkuverse_crawler summarize

# batch-size/delay 지정
python -m skkuverse_crawler summarize --batch-size 500 --delay 2.0

# gnuboard 첨부파일 referer 백필 (dry-run)
python -m skkuverse_crawler backfill-attachment-referer
python -m skkuverse_crawler backfill-attachment-referer --apply --source nano

# skku-standard 첨부 재크롤링 (dry-run)
python -m skkuverse_crawler backfill-attachments
python -m skkuverse_crawler backfill-attachments --apply --source law --limit 10

# cheme WPDM 첨부 URL 교체 (dry-run)
python -m skkuverse_crawler backfill-wpdm-attachments
python -m skkuverse_crawler backfill-wpdm-attachments --apply

# 첨부파일 메타데이터 검증
python -m skkuverse_crawler validate-attachments
python -m skkuverse_crawler validate-attachments --source cheme --no-http --json

# cleanMarkdown 렌더링 품질 검증
python -m skkuverse_crawler validate-markdown
python -m skkuverse_crawler validate-markdown --source skku-main --severity error

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
| `--source <id>` | 전체 | 특정 학과만 크롤링 (sources.json의 id) |
| `--pages <n>` | 무제한 | 최대 페이지 수 제한 |
| `--delay <ms>` | 500 | 요청 간 최소 딜레이 (밀리초) |
| **update-check** | | |
| `--days <n>` | 14 | 변경 감지 윈도우 (일) |
| `--source <id>` | 전체 | 특정 학과만 체크 |
| **backfill-content** | | |
| `--apply` | false | 실제 업데이트 (없으면 dry-run) |
| `--source <id>` | 전체 | 특정 학과만 |
| `--limit <n>` | 무제한 | 최대 문서 수 |
| **backfill-attachment-referer** | | |
| `--apply` | false | 실제 업데이트 (없으면 dry-run) |
| `--source <id>` | 전체 gnuboard | 특정 학과만 |
| `--limit <n>` | 무제한 | 최대 문서 수 |
| **backfill-attachments** | | |
| `--apply` | false | 실제 업데이트 (없으면 dry-run) |
| `--source <id>` | 전체 skku-standard | 특정 학과만 |
| `--limit <n>` | 무제한 | 최대 문서 수 |
| **backfill-wpdm-attachments** | | |
| `--apply` | false | 실제 업데이트 (없으면 dry-run) |
| `--limit <n>` | 무제한 | 최대 문서 수 |
| **validate-attachments** | | |
| `--source <id>` | 전체 | 특정 학과만 |
| `--limit <n>` | 무제한 | 최대 공지 수 |
| `--no-http` | false | HTTP 도달성 검사 스킵 |
| `--json` | false | JSON 형식 출력 |
| `--concurrency <n>` | 20 | HTTP 동시 요청 수 |
| **validate-markdown** | | |
| `--source <id>` | 전체 | 특정 학과만 |
| `--limit <n>` | 무제한 | 최대 공지 수 |
| `--severity` | all | `all`, `error`, `warning` 필터 |
| `--json` | false | JSON 형식 출력 |
| **summarize** | | |
| `--batch-size <n>` | 50 | 배치당 공지 수 |
| `--delay <sec>` | 1.0 | API 호출 간 딜레이 (초) |

## 소요시간 추정 (500ms 딜레이 기준)

| 시나리오 | 요청 수 | 소요시간 |
|----------|---------|----------|
| 평상시 incremental (새 글 0~5건) | 1~6 | ~3초 |
| --pages 3 (30건 목록+상세) | 33 | ~17초 |
| 초기 풀 크롤링 50페이지 (500건) | 550 | ~5분 |
