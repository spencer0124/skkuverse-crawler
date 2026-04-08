# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

SKKU 관련 데이터 크롤링 + 콘텐츠 정제 서비스. Python 구현 (`py/`).

## Commands

```bash
cd py
python -m skkuverse_crawler start                        # 모든 모듈 cron/interval 실행
python -m skkuverse_crawler start --module notices       # 단일 모듈
python -m skkuverse_crawler start --module bus-hssc      # HSSC 셔틀 폴링
python -m skkuverse_crawler notices --once               # 공지 1회 실행
python -m skkuverse_crawler notices --once --dept skku-main --pages 3

# 테스트 & 린트
python -m pytest tests/ -v                  # 전체 테스트
python -m pytest tests/bus_hssc/ -v         # 특정 모듈만
python -m pytest tests/ -k "test_name"      # 단일 테스트
ruff check src/                             # 린트
mypy src/                                   # 타입 체크
```

## Architecture

### 공통 패턴

**모듈형 구조**: `shared/` (DB, logger, HTTP 클라이언트) + 각 모듈 디렉토리 (notices, bus_hssc, bus_jongro)

**Strategy Pattern**: `CrawlStrategy` 인터페이스 + `departments.json` config-driven. 7개 전략: skku-standard, wordpress-api, skkumed-asp, jsp-dorm, custom-php, gnuboard, gnuboard-custom.

**Incremental Crawl**: title+date 변경 감지 → 변경분만 상세 fetch. 페이지 내 전부 DB에 존재하면 early-stop. content:null 기사 자동 재크롤링.

**HTML Cleaning**: 5단계 파이프라인 (BS4 junk 제거 → semantic 정규화 → URL 절대경로 → nh3 태그/스타일 필터링 → 빈 요소 제거).

### 모듈 시스템 (`py/src/skkuverse_crawler/`)

- `modules/base.py` — `ModuleConfig` (name, collection_name, cron_schedule 또는 interval_seconds) + `CrawlModule` Protocol
- `modules/registry.py` — 전역 모듈 레지스트리
- `cli.py` — APScheduler로 모듈 스케줄링. CronTrigger(notices) / IntervalTrigger(bus). `max_instances=1` + `coalesce=True`
- `shared/db.py` — Motor async MongoDB 싱글턴. `CRAWLER_ENV` 기반 DB suffix (`_dev`, `_test`, 또는 없음)
- `shared/bus_cache.py` — bus_cache 컬렉션 (TTL 60초 자동 만료)

### 스케줄 주기

| 모듈 | 타입 | 주기 |
|------|------|------|
| notices | CronTrigger | `*/30 * * * *` (30분) |
| bus-hssc | IntervalTrigger | 10초 |
| bus-jongro | IntervalTrigger | 40초 |

### DB 이름 규칙

`CRAWLER_ENV=production` → `skku_notices` (suffix 없음), `development` → `skku_notices_dev`, `test` → `skku_notices_test`.

## Environment

`.env` 파일 필요 (`py/.env`):
- `MONGO_URL` — MongoDB 연결 문자열 (필수)
- `MONGO_DB_NAME` — 기본: `skku_notices`
- `CRAWLER_ENV` — `production` / `development` / `test`
- `LOG_FORMAT` — `json` (기본) / `dev` (컬러 콘솔)
- `API_HSSC_URL`, `API_JONGRO02_LIST_URL`, `API_JONGRO02_LOC_URL`, `API_JONGRO07_LIST_URL`, `API_JONGRO07_LOC_URL` — 버스 API

## Testing

Python 테스트는 `py/tests/`에 위치. `respx`로 httpx 요청 목킹, `conftest.py`에서 MongoDB를 autouse fixture로 전역 목킹. `asyncio_mode = "auto"` 설정으로 async 테스트 자동 처리.

## Adding New Modules

1. `py/src/skkuverse_crawler/<module>/` 생성 (module.py, fetcher.py 등)
2. `CrawlModule` Protocol 구현 (run, shutdown, config)
3. `cli.py`의 `_start_scheduler()`에 `registry.register()` 추가
4. `shared/` 인프라 재사용 (db, logger, fetcher, bus_cache)
