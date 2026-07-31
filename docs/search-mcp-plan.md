# 검색 인프라 + MCP 서버 — 단계별 작업 계획 (크로스레포 SSOT)

직접 임베딩 기반 하이브리드 검색을 구축하고 그 위에 공개 MCP 서버를 얹는 작업의 **전체 로드맵**. 설계는 [search-architecture.md](search-architecture.md), 결정 근거는 [decisions/](decisions/README.md). skkuverse-ai 몫의 상세 체크리스트는 `skkuverse-ai/docs/internal/search-mcp-plan.md`.

**진행 원칙**: Phase 순서대로, 각 레포에서 `dev`에서 딴 feature 브랜치 → 검증 게이트 통과 → dev PR. main은 merge-only. 크롤러 코드 단계는 `ruff check src/` + `python -m pytest tests/` green 유지.

## 레포 분담 (skkuverse-ai adr-001 — 크롤러 OSS 공개 계획 반영)

| 레포 | 소유 |
|------|------|
| **skkuverse-crawler** (오픈소스 예정) | `search.json`·`sources.json` SSOT + codegen(server·ai 2곳 복사) / `notices_embedding` 오케스트레이션 모듈(입력 조합·stale 감지·`$set` — 모델 호출은 ai에 위임) / 검색 인덱스 생성 스크립트(컬렉션 소유자) |
| **skkuverse-ai** | `/api/embed`(벤더 키·모델 pin) / MCP 서버 / 검색 파이프라인 빌더 / eval 하네스 |
| **skkuverse-server** | search.json 사본 기반 TS 검색 엔드포인트 (질의 벡터는 ai에서) |

## 상태 보드 (전체)

| Phase | 레포 | 내용 | 브랜치 | 상태 |
|-------|------|------|--------|------|
| D | crawler·ai | 착수 전 문서화 (ADR·설계·계획) | — | ✅ 완료 (2026-07-29, 이관 반영 포함) |
| 0 | **ai** (A0) | 평가 체계 — 30문항 + eval 스크립트 + regex 베이스라인 | ai 레포 | ⬜ |
| 1 | **crawler** | search.json SSOT + codegen 확장 | `feat/search-ssot` | ⬜ |
| 2a | **ai** (A1) | `/api/embed` 엔드포인트 | ai 레포 | ⬜ |
| 2b | **crawler** | Atlas 인덱스 스크립트 + notices_embedding 모듈 + 백필 | `feat/notices-embedding` | ⬜ |
| 3 | **ai** (A2) | 품질 실측 — 모델 5종 비교 + 가중치 (게이트 2개) | ai 레포 | ⬜ |
| 4 | **ai** (A3) | 공개 MCP 서버 | ai 레포 | ⬜ |
| 5 | **server** | TS 검색 연동 | server 레포 | ⬜ |

의존 순서: 0 → 1 → 2a → 2b → 3 → 4. (5는 3 이후 병행 가능)

---

## Phase 0 — 평가 체계 [skkuverse-ai]

상세는 ai 레포 계획 A0. 모든 후속 판단(모델·가중치·청킹)의 잣대 — 평가 셋 30문항은 **사용자 검수 필수**.

## Phase 1 — search.json SSOT + codegen [crawler]

- [ ] 레포 루트 `search.json` 생성 (스키마: [search-architecture.md](search-architecture.md) §①)
- [ ] `py/scripts/generate_artifacts.py` 확장 — `SEARCH_JSON` 경로 + `validate_search()` + `gen_server_search()` + main() `# 8.` 블록 + `copy_to_sibling` **2곳** (`skkuverse-server/src/notices/search.json`, `skkuverse-ai/` 수신 위치는 ai와 협의 — sources 화이트리스트 사본도 ai에 추가)
- [ ] docstring·CLAUDE.md 아티팩트 표 갱신, `py/tests/scripts/test_generate_artifacts.py` 확장

**검증 게이트**: ruff+pytest green. codegen 실행 → 두 형제 레포에 사본 착지.

## Phase 2a — `/api/embed` [skkuverse-ai]

상세는 ai 레포 계획 A1. 크롤러 Phase 2b는 이 엔드포인트에 의존.

## Phase 2b — Atlas 인덱스 + notices_embedding + 백필 [crawler]

- [ ] `py/scripts/manage_search_indexes.py` — search.json에서 인덱스 2종 정의를 코드로 구성 (`notices_search` nori / `notices_vector` — 사양은 [search-architecture.md](search-architecture.md) §③). `create|update|status`, `--env`, `queryable` 폴링, 기본 dry-run + `--apply` 확인 (migrate 스크립트 패턴)
- [ ] `notices_embedding/` 모듈 — `notices_summary` 미러: `composer.py`(입력 조합 v1 + inputVersion), `query.py`(find_unembedded / find_stale — stale 3경로, failures `{"$not": {"$gte": 3}}`), `processor.py`(ai `/api/embed` 호출 — `ai_client.py` 패턴, `$set` 필드는 [search-architecture.md](search-architecture.md) §②, **BinData float32**, ⚠️ `aiSummaryAt` 절대 미기록), `module.py`(cron `40 * * * *`), `cli.py`(`embed --once --batch-size`)
- [ ] `cli.py` 등록, `shared/config.py`에 embed 엔드포인트 설정 (`AI_SERVICE_URL` 재사용)
- [ ] `pyproject.toml` — motor 3.7.x bump (pymongo≥4.10 = `Binary.from_vector`) + `uv lock`
- [ ] 테스트: `tests/notices_embedding/` — predicate dict, processor patch 스택, **aiSummaryAt 미기록 assert**, respx로 `/api/embed` 목킹
- [ ] dev DB 인덱스 + 백필 리허설 → prod 인덱스 + 백필 (~13M 토큰, 무료 한도 내)

**검증 게이트**: dev·prod embedded 수 == 대상 수, 벡터 차원/BinData 스팟체크, 인덱스 2종 `queryable: true`. ruff+pytest green.

## Phase 3 — 품질 실측 [skkuverse-ai]

상세는 ai 레포 계획 A2. **게이트 A**: 모델 5종(Voyage/KURE/BGE-M3/OpenAI/Gemini) 오프라인 비교 → [adr-002](decisions/adr-002-embedding-model.md) 결과 표 기입 + status 확정. **게이트 B**: 하이브리드 가중치 → `search.json` 갱신 + codegen 재실행 (crawler에서).

## Phase 4 — 공개 MCP 서버 [skkuverse-ai]

상세는 ai 레포 계획 A3 + `skkuverse-ai/docs/explanation/mcp-server.md` (tool 6종 계약·Ops 체크리스트). 크롤러 몫: 없음 — 단 ⚠️ **`.mcp.json` 평문 Atlas 자격증명 로테이트**(공개 블로킹)는 이 레포의 Ops.

## Phase 5 — 앱 서버 검색 연동 [skkuverse-server]

- [ ] codegen이 배달한 `src/notices/search.json` 수용 — 기존 trio 패턴 (loader + `types.ts` + boot validation, `tabconfig.provider.ts` 참조)
- [ ] 질의 임베딩: ai `POST /api/embed` 호출 (`inputType: "query"`) — 벤더 SDK 불필요
- [ ] TS $rankFusion 파이프라인 — 기존 regex 검색(`notices.search.ts`) 신규 엔드포인트 병행 후 단계적 대체
- [ ] 헬스체크에 "알려진 질의 → 정답 top-3" 스모크
- [ ] AI 챗봇 RAG는 이 검색 레이어 위 후속 (별도 계획)

## 크롤러 Ops (코드 밖)

- ⚠️ `.mcp.json` 평문 자격증명 로테이트 + 외부화 — MCP 공개 블로킹
- Atlas read-only 유저 생성 (`read@skku_notices`) → ai 레포 `MONGO_URL_MCP`
- **Atlas 티어 재점검** — auto-embed 기각으로 M10 강제 사유 소멸 ([search-architecture.md](search-architecture.md) 비용 절 참조). 티어 변경 시 `$rankFusion`(8.1+) 재확인
- OSS 공개 준비는 별도 트랙: git 히스토리 시크릿 스캔 포함

## 의도적 범위 밖 (Out of Scope)

- 중복 공지 탐지·관련 공지·클러스터링 기능 자체 — 토대(벡터 + `find_similar_notices`)까지만
- 청킹 — v1은 공지당 벡터 1개. eval에서 장문만 유독 실패하면 후속 (voyage-context-4 옵션)
- rerank-2.5 — 후속 옵션
- PyMongo Async 마이그레이션 (크롤러) — Motor EOL 대응 별도 과제. 단 ai 레포 신규 DB 코드는 처음부터 PyMongo Async
- MCP 인증(OAuth) — 익명 공개 결정. 남용 시 후속
- 앱 UI / 챗봇 구현

## 리스크 요약

| 리스크 | 대응 |
|--------|------|
| 임베딩 모델 관성 선택 (Voyage 미검증) | Phase 3 게이트 A — 후보 5종 자체 데이터 실측 (adr-002) |
| 모델 정합성 드리프트 | ai `/api/embed` 단일 초크포인트로 구조적 축소 + search.json codegen + model echo |
| fastmcp 3.x API 드리프트 | 구현 시 검증, 폴백 명세 (ai 레포 문서) |
| nori 옵션 비노출 | 문제 시 `lucene.cjk` 비교를 eval로 |
| `schedule` 컬렉션 prod 부재 | `get_academic_schedule`은 배포 전까지 안내 메시지 |
| 정제 로직 변경 → 전량 재요약·재임베딩 | search-architecture.md에 명시, 현 규모 무해 |
| 크로스레포 조율 비용 (신규) | Phase 의존 순서 명시 (0→1→2a→2b→3→4), search.json 변경은 항상 crawler codegen 경유 |
