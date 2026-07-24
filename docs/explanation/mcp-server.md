---
title: MCP 서버 — 설계 의도 (예정)
type: explanation
status: draft
owner: zoyoong124@gmail.com
last-updated: 2026-07-24
audience: public
---

# MCP 서버 — 설계 의도 (예정)

> 크롤러가 모아온 SKKU 데이터(공지·학사일정·예정 식당)를 **MCP(Model Context Protocol) 서버로 공개**하려는 설계 의도와 경계. LLM 에이전트가 "성대 오늘 공지 알려줘" 같은 질의로 이 데이터를 도구처럼 쓰게 하는 것이 목표.

> [!WARNING]
> **아직 구현 전(greenfield)이다.** 이 문서는 방향·경계를 잡는 설계 의도이며, 실제 도구 계약(tool schema)은 서버가 생기면 [reference/mcp-tools.md]로 분리해 채운다. 현재 레포의 `.mcp.json`은 **소비자 설정**(Claude Code가 MongoDB를 읽기 위한 `mongodb-mcp-server`)일 뿐, 크롤러를 공개하는 서버가 아니다.

## 왜 MCP인가

크롤러는 이미 SKKU 데이터의 정제·구조화를 끝낸 상태로 갖고 있다 (공지 요약, 학사일정, 전략별 정규화). 이 자산을 **표준 인터페이스로 열면** 앱/서버라는 기존 소비자 외에 LLM 에이전트가 직접 질의할 수 있다 — "이번 주 학사일정", "장학 관련 최근 공지 3건"처럼. MCP는 그 표준을 제공하고, 크롤러는 이미 데이터 소유자이므로 공개 지점으로 자연스럽다.

## 경계 — 무엇을 노출하고 무엇을 막나

| 원칙 | 내용 |
| --- | --- |
| **읽기 전용** | MCP 도구는 조회만. 크롤/쓰기 트리거는 노출하지 않는다 (파이프라인 무결성 보호). |
| **정제된 필드만** | `summaryOneLiner`/`summary`/`summaryPeriods` 등 소비 친화 필드 위주. 원본 `content`(비정제 HTML)·내부 필드(`detailPath`, `consecutiveFailures`)는 숨김. |
| **소스 화이트리스트** | `sources.json`에 등재된 소스만. 임의 URL 크롤 도구는 제공하지 않는다. |
| **레이트 제한** | 공개 시 per-client rate limit 필수. |

## 예상 도구 표면 (초안)

실제 스키마는 구현 시 확정. 방향만:

- `search_notices(query, sourceId?, type?, since?)` — 공지 검색/필터 (요약 필드 반환)
- `get_notice(sourceId, articleNo)` — 단건 상세
- `list_sources()` — 등재 소스 목록 (분포는 [coverage](../reference/coverage/department-coverage-analysis.md))
- `get_academic_schedule(year?)` — 학사일정 ([schema/schedule.md](../reference/schema/schedule.md))
- (예정) `search_restaurant(...)` — 식당 모듈 착지 후

반환 필드의 SSOT는 언제나 [reference/schema/notices.md](../reference/schema/notices.md) — MCP 도구는 그 스키마의 read-only 뷰다.

## 구현 시 고려

- **트랜스포트**: stdio(로컬 에이전트) vs HTTP/SSE(원격 공개). 공개 목적이면 HTTP + 인증.
- **DB 접근**: 기존 `shared/db.py` 싱글턴 재사용 (읽기 전용 커넥션 권장).
- **스키마 드리프트 방지**: 도구 반환 타입을 스키마 문서와 한 소스에서 도출(가능하면 pydantic 모델 공유).
- ⚠️ **비밀 위생**: 현재 `.mcp.json`에 Atlas 자격증명이 평문으로 있다 — 공개 서버를 만들기 전 반드시 외부화/로테이트 (문서 범위 밖, 별도 처리).

## 관련 문서

- [reference/schema/notices.md](../reference/schema/notices.md) · [reference/schema/schedule.md](../reference/schema/schedule.md) — 노출 대상 스키마
- [umbrella data-topology](https://github.com/spencer0124/skkuverse/blob/main/docs/architecture/data-topology.md) — 데이터 소유권
