---
title: Diátaxis 문서 구조 채택
type: adr
status: accepted
owner: zoyoong124@gmail.com
last-updated: 2026-07-24
audience: internal
---

# ADR 0001 — Diátaxis 문서 구조 채택

## Status

accepted (2026-07 문서 재정비 시점)

## Context

`docs/`가 플랫하게 쌓이며 문제가 생겼다: frontmatter 없음, 인덱스/컨벤션 문서 없음, DB 스키마가 3~4개 파일에 중복, 소스 개수가 문서마다 134/147/149로 갈라짐, 존재하지 않는 CLI 명령(`backfill-*`)을 문서가 안내. skkuverse-app / skkuverse-server는 이미 [Diátaxis](https://diataxis.fr/) + frontmatter + "값 복사 금지" 규칙으로 이 문제를 해결했다.

## Decision

**app/server와 동일한 컨벤션을 채택한다.** 워크스페이스 표준을 재발명하지 않는다.

- 폴더: `how-to/` · `reference/` · `explanation/` · `decisions/` · `internal/` · `archive/`. 독자 니즈 기준 분류.
- 모든 hand-written 문서에 YAML frontmatter (`title/type/status/owner/last-updated/audience`).
- **값 복사 금지, 출처를 가리켜라** — 개수·라인번호·버전은 codegen 산출물이나 코드(클래스/함수명)를 링크.
- codegen 산출물(`reference/coverage/`)은 예외 — auto-gen 배너 유지, frontmatter 없음.
- 규칙 SSOT는 [docs/README.md](../README.md).

## Consequences

- ✅ 스키마 SSOT 단일화 ([reference/schema/notices.md](../reference/schema/notices.md)) → 3~4중 중복·드리프트 제거.
- ✅ 개수·명령이 코드/코드젠을 가리켜 조용한 거짓말 방지.
- ✅ 세 레포(app/server/crawler)가 같은 구조 → 포트폴리오 일관성.
- ⚠️ 초기 이관 비용. codegen 3파일은 생성 경로가 `docs/reference/coverage/`로 바뀌어 `generate_artifacts.py` 수정이 따랐다.
