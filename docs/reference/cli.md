---
title: CLI 레퍼런스
type: reference
status: accepted
owner: zoyoong124@gmail.com
last-updated: 2026-07-24
audience: internal
---

# CLI 레퍼런스

> `skkuverse-crawler` CLI의 전체 명령·플래그. 명령 정의의 SSOT는 각 모듈의 `cli.py` (등록은 루트 `cli.py`의 `main.add_command`). 실행: `python -m skkuverse_crawler <command>` (또는 설치 시 `skkuverse-crawler <command>`).

## 명령 요약

| 명령 | 정의 위치 | 용도 |
| --- | --- | --- |
| `start` | `cli.py` | APScheduler로 모든(또는 단일) 모듈 스케줄링 |
| `notices` | `notices/cli.py` | 공지 크롤 (incremental 기본) |
| `update-check` | `notices/cli.py` | 최근 N일 공지 변경 감지 (Tier-2) |
| `validate-attachments` | `notices/cli.py` | 첨부파일 메타데이터 검증 |
| `validate-markdown` | `notices/cli.py` | `cleanMarkdown` 렌더링 품질 검증 |
| `summarize` | `notices_summary/cli.py` | AI 요약 배치 실행 |
| `schedule` | `schedule/cli.py` | 학사일정 크롤 |

## 예시

```bash
cd py

# 스케줄러 (전체 / 단일 모듈)
python -m skkuverse_crawler start
python -m skkuverse_crawler start --module notices

# 공지 크롤
python -m skkuverse_crawler notices --once                         # 1회 incremental
python -m skkuverse_crawler notices --once --all                   # incremental 무시, 전체
python -m skkuverse_crawler notices --once --source skku-main --pages 3
python -m skkuverse_crawler notices --once --delay 1000            # 요청 간 딜레이(ms)

# 변경 감지
python -m skkuverse_crawler update-check                           # 최근 14일
python -m skkuverse_crawler update-check --days 7 --source skku-main

# 검증
python -m skkuverse_crawler validate-attachments --source cheme --no-http --json
python -m skkuverse_crawler validate-markdown --source skku-main --severity error

# AI 요약
python -m skkuverse_crawler summarize                              # 기본 batch-size 50
python -m skkuverse_crawler summarize --batch-size 500 --delay 2.0 # 초기 backfill

# 학사일정
python -m skkuverse_crawler schedule --once
python -m skkuverse_crawler schedule --year 2026
```

## 옵션

| 명령 | 옵션 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `start` | `--module, -m <id>` | 전체 | 특정 모듈만 스케줄링 |
| `notices` | `--once` | false | 1회 실행 후 종료 (없으면 cron 모드) |
| | `--all` | false | incremental 무시, 전체 크롤 |
| | `--source <id>` (반복 가능) | 전체 | 특정 학과만 (`sources.json`의 id) |
| | `--pages <n>` | 무제한 | 학과당 최대 페이지 |
| | `--delay <ms>` | 500 | 요청 간 딜레이 (밀리초) |
| `update-check` | `--days <n>` | 14 | 변경 감지 윈도우 (일) |
| | `--source <id>` (반복) | 전체 | 특정 학과만 |
| `validate-attachments` | `--source <id>` (반복) | 전체 | 특정 학과만 |
| | `--limit <n>` | 무제한 | 최대 공지 수 |
| | `--no-http` | false | HTTP 도달성 검사 스킵 |
| | `--json` | false | JSON 출력 |
| | `--concurrency <n>` | 20 | HTTP 동시 요청 수 |
| `validate-markdown` | `--source <id>` (반복) | 전체 | 특정 학과만 |
| | `--limit <n>` | 무제한 | 최대 공지 수 |
| | `--severity <level>` | all | `all` / `error` / `warning` |
| | `--json` | false | JSON 출력 |
| `summarize` | `--batch-size <n>` | 50 | 배치당 공지 수 |
| | `--delay <sec>` | 1.0 | API 호출 간 딜레이 (초) |
| `schedule` | `--year <n>` | 자동 | 특정 학년도만 크롤 |
| | `--once` | (기본) | 1회 실행 후 종료 |

> [!NOTE]
> 옵션 시그니처의 SSOT는 각 `cli.py`의 `@click.option` 데코레이터다. 새 옵션을 더하면 여기도 갱신한다 (값 박제 대신 코드가 진실).

## 크롤 주기 (스케줄러 모드)

각 모듈의 cron은 `ModuleConfig`에 정의돼 있다 (예: notices `*/30`, summary 매시 20분, schedule `30 5 * * *`). 정확한 값은 각 모듈 `module.py`의 `ModuleConfig`를 본다 — [explanation/module-system.md](../explanation/module-system.md).

## 관련 문서

- [how-to/add-a-source.md](../how-to/add-a-source.md) — 소스 추가 후 크롤 확인
- [how-to/run-migrations.md](../how-to/run-migrations.md) — 일회성 마이그레이션 스크립트
- [explanation/crawl-flow.md](../explanation/crawl-flow.md) — 크롤 라이프사이클
