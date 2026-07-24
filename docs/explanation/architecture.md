---
title: Architecture
type: explanation
status: accepted
owner: zoyoong124@gmail.com
last-updated: 2026-07-24
audience: internal
---

# Architecture

> skkuverse-crawler의 구조·설계 결정·데이터 흐름. 크롤 라이프사이클의 단계별 워크스루는 [crawl-flow.md](crawl-flow.md), 모듈 프레임워크의 확장성은 [module-system.md](module-system.md). 시스템 전체(레포 경계) 그림은 [umbrella container-view](https://github.com/spencer0124/skkuverse/blob/main/docs/architecture/container-view.md).

## Overview

SKKU 관련 데이터 크롤링 + 콘텐츠 정제 서비스 (Python, `py/`). **모듈형 구조**로 여러 크롤러를 추가할 수 있다 — 현재 `notices`(공지), `notices_summary`(AI 요약 write-back), `schedule`(학사일정) 모듈이 있다. 공지는 Strategy 패턴으로 게시판 유형별 파서를 분리하고 `asyncio.Semaphore`로 학과를 병렬 크롤링한다 (소스 목록은 `sources.json` — 개수는 [coverage](../reference/coverage/department-coverage-analysis.md)).

## Directory Layout

```
py/src/skkuverse_crawler/
├── __main__.py                 ← 진입점
├── cli.py                      ← Click CLI + APScheduler (모든 모듈 스케줄링)
│
├── modules/                    ← 모듈 프레임워크 (→ explanation/module-system.md)
│   ├── base.py                 ← ModuleConfig + CrawlModule Protocol
│   └── registry.py             ← 전역 모듈 레지스트리
│
├── shared/                     ← 공통 인프라 (전 모듈 공유)
│   ├── config.py               ← 중앙집중 환경 설정 (frozen Config dataclass 싱글턴)
│   ├── db.py                   ← Motor async MongoDB 싱글턴 (env별 DB 라우팅)
│   ├── logger.py               ← structlog (json/dev 포맷)
│   ├── fetcher.py              ← httpx + retry (exponential backoff)
│   ├── html_cleaner.py         ← 6단계 HTML 정제 파이프라인
│   └── html_to_markdown.py     ← cleanHtml → GFM 변환
│
├── notices/                    ← 공지 크롤 모듈
│   ├── module.py               ← NoticesModule / NoticesUpdateCheckModule (Protocol 구현)
│   ├── cli.py                  ← notices · update-check · validate-* 서브커맨드
│   ├── orchestrator.py         ← Semaphore 병렬 실행 (run_crawl)
│   ├── models.py               ← dataclass: Notice, NoticeListItem, NoticeDetail
│   ├── normalizer.py           ← build_notice 팩토리
│   ├── dedup.py                ← incremental crawl + upsert + 인덱스 (ensure_indexes)
│   ├── update_checker.py       ← Tier-2 변경 감지 (contentHash 비교)
│   ├── parser.py · hashing.py · image_verifier.py · attachment_validator.py · markdown_validator.py · constants.py · types.py
│   ├── config/
│   │   ├── loader.py           ← sources.json 로드 + 셀렉터 검증 (load_and_validate)
│   │   └── source_ids.py       ← SourceId enum (**codegen 생성** — 수동 편집 금지)
│   └── strategies/             ← 전략 구현 (→ reference/strategies/)
│
├── notices_summary/            ← AI 요약 write-back 모듈
│   ├── module.py · processor.py (run_summary_batch) · query.py · ai_client.py · dispatch_client.py · cli.py
│
└── schedule/                   ← 학사일정 모듈
    └── module.py · models.py · repository.py (upsert_year) · fetcher_parser.py · cli.py
```

> `sources.json`/`categories.json`의 SSOT는 **레포 루트**다 (`notices/config/`에 있는 건 파생물 `source_ids.py`). codegen 흐름은 [how-to/add-a-source.md](../how-to/add-a-source.md).

## Data Flow (공지)

```
cli.py (Click / APScheduler)
  → loader.load_and_validate() → 소스 config (셀렉터 검증 + 중복 ID 체크)
  → orchestrator.run_crawl(sources, options)
    → Semaphore × crawl_department()
      → find_null_content() → 이전 실패 글 상세 재크롤
      → crawl_list(page) → 목록
      → find_existing_meta() + should_continue() → incremental 판단
      → crawl_detail() → 상세
      → build_notice() → clean_html → contentText → cleanMarkdown → contentHash → 이미지 검증
      → upsert_notice() / update_with_history() → inserted | updated | touched
  → Summary logging → close_client()

[update-check] update_checker.run_update_check() → 최근 N일 재fetch → contentHash 비교 → 변경분 갱신
[summarize]   notices_summary → 미요약/stale 조회 → AI 호출 → summary* $set (→ reference/schema/notices.md)
```

## Key Design Decisions

### Centralized Config (`shared/config.py`)

모든 `os.getenv()` 호출을 한 곳에 집중 (skkuverse-server의 config 패턴을 Python으로 포팅). frozen `Config` dataclass 싱글턴 + `CrawlerEnv` enum. `init_config()`이 `load_dotenv(override=False)`로 시스템 ENV를 `.env`보다 우선(Docker 안전), 비-test 모드에서 `MONGO_URL` 누락 시 `SystemExit`(fail-fast). DB 이름 env 라우팅은 `_db_name()` — 자세히는 [reference/schema/notices.md](../reference/schema/notices.md) + 환경변수는 [CLAUDE.md](../../CLAUDE.md).

### Strategy Pattern (config-driven)

`CrawlStrategy` 추상 베이스(`crawl_list()` + `crawl_detail(ref)`) + `sources.json`의 `strategy` 필드 매핑. selectors를 config에 두어 같은 전략이라도 학과별 DOM 차이를 JSON 변경만으로 대응 → "소스 추가하는 단 하나의 길". 근거는 [ADR 0002](../decisions/0002-config-driven-strategy-pattern.md), 전략별 스펙은 [reference/strategies/](../reference/strategies/).

### Incremental Crawl + Smart Change Detection

1페이지 목록은 항상 fetch하되 DB 기존 메타(title/date)와 비교 → **변경된 글만** 상세 fetch + upsert. 변경 없는 글은 `bulk_touch_notices()`로 views/crawledAt만 갱신. 페이지 내 모든 글이 DB에 있으면 early-stop.

### Error Handling

| 상황 | 처리 |
|------|------|
| 목록 fetch 실패 (5xx/timeout) | retry → 실패 시 해당 학과 skip |
| 상세 1건 fetch 실패 | `content: None`으로 저장, 나머지 계속 |
| 파싱 에러 | 해당 글 skip, 경고 로깅 |
| `content: None`인 기존 글 | 다음 사이클에서 상세 재크롤 시도 |

### Modular Framework

각 모듈은 `CrawlModule` Protocol을 구현하고 `cli.py`에서 APScheduler로 스케줄링된다 → 새 데이터 도메인(식당 등)을 같은 패턴으로 추가. [ADR 0003](../decisions/0003-modular-crawl-framework.md) / [module-system.md](module-system.md).

## 저장소·환경

- **MongoDB** 스키마·인덱스·DB 라우팅: [reference/schema/notices.md](../reference/schema/notices.md), [reference/schema/schedule.md](../reference/schema/schedule.md) (여기서 중복하지 않음)
- **환경변수**: `shared/config.py`가 SSOT — 목록은 [CLAUDE.md](../../CLAUDE.md)의 Environment
- **CLI 실행 모드**: [reference/cli.md](../reference/cli.md)

## 관련 문서

- [crawl-flow.md](crawl-flow.md) — 크롤 라이프사이클 워크스루
- [module-system.md](module-system.md) — 모듈 프레임워크
- [reference/schema/notices.md](../reference/schema/notices.md) — 저장 스키마
