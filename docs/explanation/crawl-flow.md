---
title: Crawl Flow
type: explanation
status: accepted
owner: zoyoong124@gmail.com
last-updated: 2026-07-24
audience: internal
---

# Crawl Flow

> SKKU 각 학과/부서 공지를 자동 수집해 MongoDB에 저장하는 크롤 라이프사이클을 단계별로 설명한다. 코드 구조·설계 결정은 [architecture.md](architecture.md), 명령·플래그는 [reference/cli.md](../reference/cli.md).

## 1단계: 스케줄러

```bash
python -m skkuverse_crawler start
```

`cli.py`의 `start` → 스케줄러가 등록된 모듈들을 각자의 `cron_schedule`에 따라 `mod.run()` 호출한다. 현재 등록 모듈: `NoticesModule`(공지), `NoticesUpdateCheckModule`(변경 감지), `NoticesSummaryModule`(AI 요약), `ScheduleModule`(학사일정). **각 주기의 SSOT는 그 모듈 `module.py`의 `ModuleConfig`** (값 박제 대신 코드를 본다 — 요약은 [reference/cli.md](../reference/cli.md)).

- `max_instances=1` + `coalesce=True` — 이전 실행이 안 끝났으면 중복 실행 없이 건너뜀 (과부하 방지)
- `misfire_grace_time` — 스케줄을 너무 늦게 놓치면 건너뜀

## 2단계: Orchestrator

`NoticesModule.run()` →

```python
sources = load_and_validate()          # sources.json 로드 + 셀렉터 검증
results = await run_crawl(sources, options)
```

`run_crawl()` (orchestrator.py)이 하는 일:

1. MongoDB 연결 + 인덱스 보장 (`ensure_indexes`)
2. `asyncio.Semaphore`로 **동시 크롤 학과 수 제한** (병렬성 상한은 코드 상수)
3. 각 학과별 `_crawl_department()`

## 3단계: 학과 하나를 크롤링

### 3-1. null content 재크롤 (복구)

`find_null_content()`로 이전에 본문을 못 가져온(content=null) 공지를 먼저 상세 재시도 — 네트워크 에러 등으로 실패한 글 복구.

### 3-2. 목록 순회 (메인 루프)

`strategy.crawl_list(source, page)`로 목록 페이지를 1, 2, 3… 순회. 각 페이지에 공지 메타(제목·날짜·글번호)가 있다.

**Strategy Pattern** — 학과마다 웹사이트 구조가 달라 전략으로 분리한다. `sources.json`의 `strategy` 문자열이 실제 전략 클래스로 매핑되며, 새 학과는 기존 전략이면 JSON 한 줄, 구조가 다르면 새 전략 클래스만 추가하면 된다. 전략 목록·스펙은 [reference/strategies/](../reference/strategies/), 분포 SSOT는 [coverage](../reference/coverage/department-coverage-analysis.md).

### 3-3. Incremental 크롤 — 똑똑하게 건너뛰기

매번 전체를 가져오면 낭비라, 변경분만 가져온다:

```
[1페이지] 새 글 2 + 기존 8 → 새 글만 상세 크롤, 다음 페이지로
[2페이지] 전부 기존 글    → STOP (더 뒤로 갈 필요 없음)
```

`find_existing_meta()` + `should_continue()`로 판단. 기존 글의 제목/날짜가 바뀌면 "변경됨". 목록에서 제목이 `...`로 잘린 경우는 DB 전체 제목 앞부분과 비교해 오탐 방지.

### 3-4. 상세 크롤 + 정규화

새/변경 공지에 대해 `crawl_detail()` → `build_notice()`가 하나의 공지를 **본문 4종 + 해시**로 변환한다:

```
원본 HTML
  ├ clean_html()             → cleanHtml     (정제 HTML)
  ├ _text_from_clean_html()  → contentText   (순수 텍스트)
  ├ html_to_markdown()       → cleanMarkdown (마크다운)
  ├ normalize_content_urls() → content       (URL 절대경로화한 원본)
  └ compute_content_hash()   → contentHash   (변경 감지용 해시)
```

각 필드의 용도는 [reference/schema/notices.md §본문 필드 4종](../reference/schema/notices.md). 크롤 시점에 한 번만 변환해두면 소비자(앱/검색/AI)가 매번 변환하지 않아도 된다.

### 3-5. DB 저장

| 상황 | 동작 |
|------|------|
| 새 공지 | `upsert_notice()` — `articleNo + sourceId` 기준 insert |
| 변경된 공지 | `update_with_history()` — 본문 업데이트 + `editHistory`에 이력 기록 |
| 변경 없는 공지 | `bulk_touch_notices()` — `views`/`crawledAt`만 갱신 |

## 전체 흐름

```
[스케줄러 트리거]
  → run_crawl(sources)
    ├ 학과 A ┐
    ├ 학과 B ┤  (Semaphore로 동시 학과 수 제한)
    ├ 학과 C ┘
    ▼ (각 학과)
    _crawl_department()
      ├ 1. content=null 이전 실패 공지 복구
      ├ 2. 목록 1페이지 → DB 비교 → 전부 알면 STOP / 새·변경 글이면 상세
      ├ 3. 목록 2, 3페이지… (새 글 없을 때까지)
      └ 4. crawl_detail → build_notice(본문4종+해시) → upsert/update
```

## 관련 문서

- [architecture.md](architecture.md) — 구조·설계 결정
- [reference/schema/notices.md](../reference/schema/notices.md) — 저장 필드
- [reference/strategies/](../reference/strategies/) — 전략별 스펙
