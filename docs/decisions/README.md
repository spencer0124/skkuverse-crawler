# Architecture Decision Records (ADR)

검색 인프라·MCP 서버 작업부터 도입한 결정 기록. 각 ADR은 **왜 이 선택을 했는지**와 **언제 재검토해야 하는지**를 남긴다 — 나중에 "왜 이렇게 했었지?"에 문서로 답하기 위함.

## 양식

`상태 → 맥락 → 결정 → 근거 → 대안과 기각 사유 → 재검토 조건` 순. 상태는 `제안됨` / `잠정 채택` / `채택됨` / `대체됨(→ adr-NNN)` 중 하나.

## 목록

| ADR | 제목 | 상태 |
|-----|------|------|
| [adr-001](adr-001-direct-embedding.md) | 직접 임베딩 (Atlas auto-embed 미채택) | **대체됨 (→ adr-007)** |
| [adr-002](adr-002-embedding-model.md) | 임베딩 모델 — Voyage 4 시리즈 | **채택됨** (2026-08-01, 게이트 A 실측 완료) |
| [adr-003](adr-003-hybrid-search-atlas.md) | 하이브리드 검색 — Atlas Search(nori) + Vector Search + $rankFusion | 채택됨 (2026-08-01 개정) |
| [adr-004](adr-004-mcp-server.md) | MCP 서버 — 크롤러 레포 내 모듈, fastmcp, 익명 공개 HTTP | 대체됨 (→ skkuverse-ai adr-001) |
| [adr-005](adr-005-hakbu-board-remap.md) | 학부대학 게시판 개편 — hakbu 단일 복구 + 포털연동 슬라이스 폐기 | 채택됨 |
| [adr-006](adr-006-core-plugin-split.md) | 코어/플러그인 분리 — 무상태 코어 + 3-포트 seam + 단일 배포물 extras | **제안됨** |
| [adr-007](adr-007-atlas-auto-embedding.md) | **Atlas Automated Embedding 채택** (adr-001 대체) | **채택됨** (2026-08-01) |

관련 문서: [search-architecture.md](../search-architecture.md) (설계), [search-mcp-plan.md](../search-mcp-plan.md) (단계별 작업 계획), [core-plugin-architecture.md](../core-plugin-architecture.md) (설계) + [core-plugin-plan.md](../core-plugin-plan.md) (단계별 작업 계획). MCP 서버 문서는 `skkuverse-ai/docs/explanation/mcp-server.md`로 이관됨 (크롤러 OSS 공개 계획 때문 — skkuverse-ai adr-001 참조).

> **검색 인프라 결정 흐름** (2026-08-01 기준): adr-001(직접 임베딩) → **adr-007(auto-embed)로 뒤집힘**. 근거는 prod 클러스터 실측이며 원본 기록은 `skkuverse-ai/docs/internal/autoembed-verification.md`. 모델 비교 실측은 `skkuverse-ai/eval/results.md`. `skkuverse-ai/docs/explanation/embedding-service.md`(`/api/embed` 설계)는 adr-007 로 **불필요해져 폐기**됨.
