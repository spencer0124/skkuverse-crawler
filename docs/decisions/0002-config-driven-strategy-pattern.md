---
title: config-driven Strategy Pattern으로 소스 추가 단일화
type: adr
status: accepted
owner: zoyoong124@gmail.com
last-updated: 2026-07-24
audience: internal
---

# ADR 0002 — config-driven Strategy Pattern

## Status

accepted (백필 — 구조 결정 명문화)

## Context

SKKU는 학과마다 게시판 구조가 제각각이다 (표준 게시판, gnuboard, WordPress, ASP, JSP 기숙사, custom PHP…). 150개 가까운 소스를 각각 다른 파싱 코드로 붙이면 소스 추가가 곧 코드 변경이 되고, 중복·회귀가 폭증한다.

## Decision

**게시판 유형은 전략(strategy)으로 캡슐화하고, 소스별 차이는 `sources.json` config로 흡수한다.**

- `CrawlStrategy` 추상 베이스: `crawl_list()` + `crawl_detail(ref)`. 유형별 구현이 `notices/strategies/`에 하나씩.
- 소스는 `sources.json` 엔트리 하나 — `strategy` 필드로 전략을 고르고, `selectors`/`pagination`/`baseUrl`을 config에 둔다.
- 같은 전략이라도 학과별 DOM 차이는 **JSON 변경만으로** 대응. 새 유형이 나올 때만 새 전략 클래스.
- `sources.json`은 SSOT이고, codegen(`generate_artifacts.py`)이 여기서 `SourceId` enum·서버 config·커버리지 문서를 파생한다.

## Consequences

- ✅ "소스 추가하는 단 하나의 길" — 기존 유형이면 JSON 한 줄 + codegen ([how-to/add-a-source.md](../how-to/add-a-source.md)).
- ✅ 파싱 로직이 유형당 한 곳 → 회귀 표면 최소화.
- ✅ 개수·분포가 codegen 산출물로 자동 집계 → 문서 드리프트 없음.
- ⚠️ config 검증이 중요해짐 — `loader.load_and_validate()` + codegen의 양방향 검증이 잘못된 엔트리를 부팅/생성 단계에서 잡는다.
- ⚠️ 비표준 사이트(화학과 등)는 전략 확장(옵션 파서)이 필요할 수 있음 — [reference/strategies/](../reference/strategies/).
