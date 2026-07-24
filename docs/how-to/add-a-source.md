---
title: 학과/기관 소스 추가하기
type: how-to
status: accepted
owner: zoyoong124@gmail.com
last-updated: 2026-07-24
audience: internal
---

# 학과/기관 소스 추가하기

> 새 학과/부서 게시판을 크롤 대상에 추가하는 절차. 소스 데이터의 SSOT는 레포 루트 `sources.json`이고, 나머지(서버/Docker/문서)는 codegen이 파생한다.

## 개요

소스 하나 = `sources.json`의 엔트리 하나. 편집 후 **codegen을 돌려야** `SourceId` enum·서버 config·커버리지 문서가 갱신된다. 기존 전략이 맞으면 코드는 안 건드린다 (config-driven — [ADR 0002](../decisions/0002-config-driven-strategy-pattern.md)). 게시판 구조가 새로우면 전략 추가가 먼저 필요하다 ([add-a-module.md](add-a-module.md)의 전략 파트 / [reference/strategies/](../reference/strategies/)).

## 단계

1. **`sources.json`(레포 루트) 편집** — 엔트리 추가:
   - 필수: `id`, `name`, `strategy`, `campus`, `college`, `appCategory`, `crawlEnabled`
   - 크롤 설정: `baseUrl`, `selectors`, `pagination` (전략별 형태는 [reference/strategies/](../reference/strategies/)의 해당 전략 문서 예시 참조)
   - `campus` 유효값은 `generate_artifacts.py`의 `VALID_CAMPUSES`, `appCategory`는 `categories.json`의 id에서 도출
2. **새 카테고리가 필요하면 `categories.json`도 편집** (탭 순서 = 배열 순서, `tabMode` picker/fixed)
3. **codegen 실행**:
   ```bash
   cd py && python scripts/generate_artifacts.py
   ```
   → `SourceId` enum, `py/generated/*`, [coverage 문서](../reference/coverage/department-coverage-analysis.md) 갱신. 형제 레포(skkuverse-server)가 존재하면 server config가 자동 복사됨.
4. **검증 크롤** (dev):
   ```bash
   python -m skkuverse_crawler notices --once --source <새-id> --pages 1
   ```
   목록·상세·첨부가 정상 파싱되는지 확인.

## 트러블슈팅

- codegen이 검증 에러(`category ... matches 0 departments` 등)를 내면 `sources.json` ↔ `categories.json` 정합성을 맞춘다 (`appCategory`가 존재하는 category id인지).
- 셀렉터가 안 맞으면 목록이 0건. 해당 전략 문서의 셀렉터 예시와 대상 사이트 DOM을 대조.
- `crawlEnabled: false`면 스케줄 크롤에서 제외된다 (수동 `--source`로는 실행 가능).

> [!WARNING]
> `CRAWL_SOURCE_FILTER` env를 프로덕션에 두지 말 것 — `crawlEnabled`를 덮어써 나머지 소스를 침묵 차단한다 (과거 인시던트 — [archive/known-issues-2026h1.md](../archive/known-issues-2026h1.md)).

## 관련 문서

- [reference/strategies/](../reference/strategies/) — 전략별 셀렉터 스펙
- [add-a-module.md](add-a-module.md) — 새 전략/모듈이 필요할 때
- [reference/cli.md](../reference/cli.md) — 크롤 명령
