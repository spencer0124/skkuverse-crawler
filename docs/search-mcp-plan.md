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

> [!IMPORTANT]
> **2026-08-01 재구성** — [adr-007](decisions/adr-007-atlas-auto-embedding.md)(Atlas Automated Embedding 채택)로 Phase 2a 가 **삭제**되고 2b 가 대폭 축소됐다. 크롤러는 벡터를 만들지도 저장하지도 않는다. 근거 실험은 `skkuverse-ai/docs/internal/autoembed-verification.md`.

| Phase | 레포 | 내용 | 브랜치 | 상태 |
|-------|------|------|--------|------|
| D | crawler·ai | 착수 전 문서화 (ADR·설계·계획) | — | ✅ 완료 (2026-07-29) |
| 0 | **ai** (A0) | 평가 체계 — 26문항 + eval 하네스 + regex 베이스라인 | `feat/search-eval` | ✅ **완료 (2026-07-29)** |
| 0.5 | **ai** | 모델 비교 (게이트 A) + auto-embed 실검증 | `feat/search-eval` | ✅ **완료 (2026-08-01)** |
| 1 | **crawler** | search.json SSOT + codegen 확장 | `feat/search-ssot` | ⬜ |
| ~~2a~~ | ~~ai (A1)~~ | ~~`/api/embed` 엔드포인트~~ | — | ❌ **삭제 (adr-007)** |
| 2b | **crawler** | Atlas autoEmbed 인덱스 + `embeddingInput` 조합 + 백필 | `feat/notices-embedding` | ⬜ |
| 3 | **ai** (A2) | 가중치 스윕 (게이트 B) — 게이트 A 는 0.5 에서 완료 | ai 레포 | ⬜ |
| 4 | **ai** (A3) | 공개 MCP 서버 | ai 레포 | ⬜ |
| 5 | **server** | TS 검색 연동 | server 레포 | ⬜ |

의존 순서: ~~0 → 1 → 2a → 2b → 3 → 4~~ → **0 → 1 → 2b → 3 → 4**. (5는 3 이후 병행 가능)

> Phase 0.5 는 계획에 없던 단계다. 게이트 A(모델 비교)가 원래 Phase 3 소속이었는데 **Atlas 인덱스 없이 오프라인으로 잴 수 있어** 순서를 앞당겼다 — 계획서의 "의존 순서"가 실제보다 빡빡했던 셈이다.

---

## Phase 0 / 0.5 — 평가 체계 + 모델 확정 [skkuverse-ai] ✅ 완료

상세는 ai 레포 계획 A0, 수치는 `skkuverse-ai/eval/results.md`.

- 평가 셋 **26문항**(keyword5/paraphrase5/concept5/scoped4/english4/typo3) + 마감일 전용 4문항 분리. 사용자 검수 완료
- regex 베이스라인 hit@1 **0.192**
- 게이트 A: Voyage `voyage-4-large` **0.654** vs OpenAI 3-large **0.577** — MRR@10 0.724 vs 0.718 로 **동률**. Voyage 확정 (adr-002)
- auto-embed 실검증 → adr-007 (`skkuverse-ai/docs/internal/autoembed-verification.md`)

## Phase 1 — search.json SSOT + codegen [crawler]

- [ ] 레포 루트 `search.json` 생성 (스키마: [search-architecture.md](search-architecture.md) §① — adr-007 로 `embedding` 섹션이 `model`/`quantization`/`inputVersion` 3개로 축소됨)
- [ ] `py/scripts/generate_artifacts.py` 확장 — `SEARCH_JSON` 경로 + `validate_search()` + `gen_server_search()` + main() 블록 + `copy_to_sibling` **2곳**: `skkuverse-server/src/notices/search.json`, **`skkuverse-ai/app/generated/search.json`** (ai 측 확정 경로 — 수신 디렉터리는 이미 생성·커밋돼 있다). sources 화이트리스트 사본도 ai 에 추가
- [ ] docstring·CLAUDE.md 아티팩트 표 갱신 (현재 표는 7개라 적혀 있으나 실제 9행), `py/tests/scripts/test_generate_artifacts.py` 확장

⚠️ `copy_to_sibling()` 은 **대상의 부모 디렉터리가 없으면 조용히 건너뛴다** (`-- Skipped` 한 줄, 에러 없음, 반환값 없음). ai 측 `app/generated/` 는 이 함정 때문에 미리 만들어 커밋해뒀다.

⚠️ `main()` 의 검증 프리앰블은 SSOT 파일 누락 시 `sys.exit(1)` 한다 — `SEARCH_JSON` 을 그 튜플에 넣으면 **모든 codegen 실행에 이 파일이 필수**가 된다.

**검증 게이트**: ruff+pytest green. codegen 실행 → 두 형제 레포에 사본 착지.

## Phase 2b — autoEmbed 인덱스 + `embeddingInput` 조합 [crawler]

> adr-007 로 **`ai_client.py`·벡터 `$set`·실패 카운터·9시간 백필이 전부 삭제**됐다. 크롤러가 하는 일은 문자열 조합 + `$set` 뿐이다.

- [ ] `py/scripts/manage_search_indexes.py` — search.json 에서 인덱스 2종을 코드로 구성 (`notices_search` nori / `notices_vector` **autoEmbed** — 사양은 [search-architecture.md](search-architecture.md) §③). `create|update|status`, `--env`, `queryable` 폴링, 기본 dry-run + `--apply` (migrate 스크립트 패턴). `create_search_index()` 는 설치된 pymongo 4.16 에 이미 있음
- [ ] `embeddingInput` 조합기 — `title + category + summaryOneLiner + summary + contentText`, 16,000자 캡. **한 곳에 두고 두 곳에서 호출**한다:
  - `modules/notices/normalizer.py` `to_notice()` — 크롤 시점 (title/category/contentText 확보 상태)
  - `notices_summary/processor.py` 의 `$set` — 요약이 붙은 뒤 재조합 (요약은 크롤보다 늦게 온다)
- [ ] `$set` 필드는 §② — `embeddingInput` / `embeddingInputVersion` / `embeddingInputHash` / `embeddingInputAt`. ⚠️ **`aiSummaryAt` 절대 미기록** (서버 FCM 디스패치 게이트)
- [ ] 백필 스크립트 (일회성) — 기존 문서에 `embeddingInput` 채우기. `ContentRefreshed` 우회 경로와 6,714건 기존 문서는 크롤에 편승할 수 없다. `cleanup_summary_fields.py` 의 dry-run + `--apply` 패턴
- [ ] 테스트: 조합기 단위 테스트(캡·null 필드·순서), **`aiSummaryAt` 미기록 assert**, 재조합 predicate
- [ ] dev DB 인덱스 + 리허설 → prod

**검증 게이트**: `embeddingInput` 보유 수 == 대상 수, 인덱스 2종 `queryable: true`, `query.text` 왕복 스모크. ruff+pytest green.

> **새 모듈·크론이 필요한가?** 아마 아니다. 조합기를 기존 두 쓰기 경로에 얹고 일회성 백필 스크립트를 돌리면 `notices_embedding/` 모듈도 `40 * * * *` 크론도 없이 끝난다. 자가 치유 리컨실러가 필요하다고 판단될 때만 모듈로 승격한다.

## Phase 3 — 품질 실측 [skkuverse-ai]

상세는 ai 레포 계획 A2.

- ~~**게이트 A**: 모델 5종 오프라인 비교~~ → ✅ **Phase 0.5 에서 완료** (2종 실측, [adr-002](decisions/adr-002-embedding-model.md) 결과 표 기입 + status 확정). 미측정 3종의 사유도 ADR 에 기록
- **게이트 B**: 하이브리드 가중치 스윕 → `search.json` 갱신 + codegen 재실행 (crawler 에서). **Phase 2b(인덱스 생성) 이후에만 가능** — `text-only(nori)` 변형을 재려면 Atlas Search 인덱스가 있어야 한다

## Phase 4 — 공개 MCP 서버 [skkuverse-ai]

상세는 ai 레포 계획 A3 + `skkuverse-ai/docs/explanation/mcp-server.md` (tool 6종 계약·Ops 체크리스트). 크롤러 몫: 없음 — 단 ⚠️ **`.mcp.json` 평문 Atlas 자격증명 로테이트**(공개 블로킹)는 이 레포의 Ops.

## Phase 5 — 앱 서버 검색 연동 [skkuverse-server]

- [ ] codegen이 배달한 `src/notices/search.json` 수용 — 기존 trio 패턴 (loader + `types.ts` + boot validation, `tabconfig.provider.ts` 참조)
- [ ] ~~질의 임베딩: ai `POST /api/embed` 호출~~ → **불필요** (adr-007). `$vectorSearch` 에 `query: {text}` + `model` 을 그대로 넘긴다
- [ ] TS $rankFusion 파이프라인 — 기존 regex 검색(`notices.search.ts`) 신규 엔드포인트 병행 후 단계적 대체
- [ ] ⚠️ **결과 dedup** — 정규화 제목 기준. 안 하면 `limit` 안이 같은 공지 사본으로 찬다 (코퍼스 67% 중복)
- [ ] 헬스체크에 "알려진 질의 → 정답 top-3" 스모크
- [ ] AI 챗봇 RAG는 이 검색 레이어 위 후속 (별도 계획)

## 크롤러 Ops (코드 밖)

- ⚠️ `.mcp.json` 평문 자격증명 로테이트 + 외부화 — MCP 공개 블로킹
- ✅ Atlas read-only 유저 생성 (`skku_read`, `read@skku_notices`) → ai 레포 `MONGO_URL_MCP` — **완료 2026-07-29**, 쓰기·타 DB 접근 거부까지 검증
- **Atlas 티어 재점검** — ~~auto-embed 기각으로 M10 강제 사유 소멸~~ → **adr-007 로 auto-embed 를 채택했으므로 M10+ 오토스케일링 조건이 다시 살아난다.** 2026-08-01 실측에서 이 클러스터는 인덱스 생성이 그대로 수락됐으나, 티어를 바꾸면 재확인 필요. ~~`$rankFusion`(8.1+)~~ → **8.0 도입 기능이라 현 클러스터(8.0.29)에서 동작** (잘못된 버전 근거 정정)
- **클러스터 8.3 업그레이드 검토** — Atlas 네이티브 `$rerank` 사용 조건. 현재 8.0.29 에서 `$rerank is not allowed`. RAG 품질 개선 여지가 큰 항목(vector 대비 +10.82% by MongoDB)이라 후속 과제로 등록
- **`date` 포맷 정규화** — 829건(12.6%)이 `"2026-07-29 16:18"` 형태. adr-003 의 사전식 범위 필터 상한이 마지막 하루를 누락시킨다. **크롤러 소유 선행 과제**
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
| ~~임베딩 모델 관성 선택 (Voyage 미검증)~~ | ✅ **해소** — 게이트 A 실측 완료, Voyage 확정 (adr-002) |
| ~~모델 정합성 드리프트~~ | ✅ **구조적 소멸** — autoEmbed 인덱스 정의 하나에서 색인·질의 모델이 나온다 (adr-007) |
| **`find_similar_notices` 가 비문서화 내부 네임스페이스 의존** | 주 기능(`search_notices`)은 공식 경로만 사용 → 내부 구조가 깨져도 검색은 안 죽는다. 상세는 adr-007 "감수하는 것" |
| **auto-embed 초기 빌드 처리량 미측정** | 50건 표본(70초)으로 6,714건을 외삽할 수 없음. Phase 2b 백필 시 실측 |
| **Atlas 임베딩 과금이 조직 인보이스로** | Voyage 무료 200M 이 Atlas 경로에도 적용되는지 미확인. Phase 2b 백필 후 청구서 확인 |
| **`date` 포맷 혼재 → 범위 필터 상한 누락** | 크롤러 정규화 선행 (Ops 절) |
| fastmcp 3.x API 드리프트 | 구현 시 검증, 폴백 명세 (ai 레포 문서) |
| nori 옵션 비노출 | 문제 시 `lucene.cjk` 비교를 eval로 |
| `schedule` 컬렉션 prod 부재 | `get_academic_schedule`은 배포 전까지 안내 메시지 |
| 정제 로직 변경 → 전량 재요약·재임베딩 | search-architecture.md에 명시, 현 규모 무해 |
| 크로스레포 조율 비용 (신규) | Phase 의존 순서 명시 (0→1→2a→2b→3→4), search.json 변경은 항상 crawler codegen 경유 |
