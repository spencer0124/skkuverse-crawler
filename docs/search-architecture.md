# Search Architecture — 공통 검색 인프라 설계

앱 자연어 검색·AI 챗봇·공개 MCP 서버가 **같은 검색 인프라를 공유**하기 위한 설계. 결정 배경은 [decisions/](decisions/README.md) (adr-001~003 + skkuverse-ai adr-001), 작업 순서는 [search-mcp-plan.md](search-mcp-plan.md) 참조.

> **상태**: 설계 확정, 구현 전. **2026-08-01 [adr-007](decisions/adr-007-atlas-auto-embedding.md) 로 임베딩 방식이 뒤집혀 ②가 재작성됨.** 구현되면 "예정" 표기를 걷어내고 코드 참조로 대체할 것.
>
> **레포 분담** (skkuverse-ai adr-001, 크롤러 OSS 공개 계획 반영): 이 레포는 **쓰기 측**(SSOT·codegen·`embeddingInput` 조합·인덱스 생성)을, **skkuverse-ai**는 **질의 측**(MCP 서버·검색 파이프라인·eval)을 소유한다.

## 공통 모듈 — 겹침의 3개 레이어

원칙: **크롤러는 임베딩할 텍스트만 만들고, 벡터는 Atlas 가 만든다** ([adr-007](decisions/adr-007-atlas-auto-embedding.md)).

| 레이어 | 소유/위치 | 소비자 |
|--------|----------|--------|
| ① 설정 SSOT | 레포 루트 `search.json` (예정) → codegen이 **skkuverse-server·skkuverse-ai 양쪽**에 사본 복사 | 3개 레포 전부 |
| ② 임베딩 입력 (write) | 크롤러가 `embeddingInput` **텍스트 필드**를 조합해 `$set`. **API 호출 없음, 벡터 없음** — Atlas `autoEmbed` 인덱스가 자동 임베딩·동기화 | Atlas 내부 (앱은 벡터를 직접 다루지 않음) |
| ③ 검색 파이프라인 (read) | **skkuverse-ai** — `$rankFusion` 빌더·eval. 질의는 `$vectorSearch { query: {text}, model }` 로 텍스트를 그대로 넘김 | MCP 서버(ai 내부), 앱 서버, eval |

**드리프트 방어**: 원래 세 소비자가 각자 임베딩을 만들 계획일 때는 4중 방어(SSOT+codegen+model echo+스모크)가 필요했다. adr-007 이후 **색인 모델과 질의 모델이 인덱스 정의 하나에서 나오므로 드리프트가 구조적으로 불가능**하다. 소비자가 모델을 지정할 여지 자체가 없다. `search.json` 이 배포하는 것은 이제 **인덱스명·하이브리드 가중치·`inputVersion`** 이지 모델 pin 이 아니다.

> ⚠️ **비대칭 임베딩을 잃었다.** 원안은 문서 `voyage-4-large` + 질의 `voyage-4-lite` 였는데, `autoEmbed` 인덱스는 `model` 을 하나만 받는다. `voyage-4-large` 단일로 간다 (adr-002 개정).

## ① search.json SSOT

레포 루트, `sources.json`과 같은 방식으로 `py/scripts/generate_artifacts.py`가 검증 + 형제 레포 복사 (server·ai 2곳). 담는 것:

```jsonc
{
  "embedding": {
    "documentModel": "voyage-4-large",   // adr-002 — Phase 3 실측 후 확정 (후보 5종)
    "queryModel": "voyage-4-lite",
    "dimensions": 1024,
    "similarity": "dotProduct",          // Voyage 출력이 L2-normalized라 cosine과 동일 순위
    "inputVersion": 1                    // compose_embedding_input 조합 규칙 버전
  },
  "indexes": { "search": "notices_search", "vector": "notices_vector" },
  "hybrid": { "weights": { "text": 1.0, "vector": 1.0 }, "pipelineLimit": 50 }  // Phase 3에서 확정
}
```

모델명은 env로 오버라이드하지 않는다 — 어긋나면 에러 없이 검색 품질만 조용히 무너지는 유형의 설정이므로, 변경 경로를 search.json 수정 + codegen 재실행 하나로 고정.

## ② 임베딩 필드 스키마 (notices 컬렉션에 추가 예정)

| 필드 | 타입 | 설명 |
|------|------|------|
| `contentEmbedding` | BinData(vector, float32) | 문서 벡터. `Binary.from_vector` — 문서당 ~4.1KB (plain array 대비 1/3) |
| `embeddingInput` | string | 임베딩된 실제 텍스트 (조합 결과 저장 — 디버깅용. 용량 아까우면 생략 가능: inputVersion으로 재구성 가능) |
| `embeddingModel` | string | 생성 모델명. 모델 전환 시 미마이그레이션 문서 추적 |
| `embeddingContentHash` | string | 임베딩 당시의 `contentHash` — stale 판정 |
| `embeddingAt` | datetime | 임베딩 시각 |
| `embeddingFailures` | int | 실패 카운터 (`summaryFailures`와 동일 관용구) |

**입력 조합 v1** (`compose_embedding_input`): `title + category + summaryOneLiner + summary + contentText`, 16,000자 캡. 조합 규칙 변경 시 `inputVersion` 올림.

**stale 판정** — 재임베딩 세 경로 (`notices_summary` predicate 관용구 미러):

1. 본문 수정: `embeddingContentHash != contentHash`
2. 요약이 나중에 붙음: `summaryAt > embeddingAt` (요약 매시 :20, 임베딩 :40 — 크롤 직후엔 요약 없이 임베딩될 수 있음)
3. 모델 전환: `embeddingModel != 현재 documentModel`

실패 가드는 `{"$not": {"$gte": 3}}` (필드 부재 문서도 매치). ⚠️ 임베딩 processor는 **`aiSummaryAt`을 절대 기록하지 않는다** — 서버 FCM 디스패치 게이트라 기록 시 스퓨리어스 푸시 발생.

## ③ 인덱스 + 하이브리드 파이프라인

인덱스 정의는 별도 JSON 파일 없이 `py/scripts/manage_search_indexes.py`(예정, 이 레포 — 컬렉션 소유자·readWrite 크리덴셜)가 search.json에서 **코드로 구성**:

- `notices_search` (Atlas Search): `lucene.nori`, string 필드 title/summary/summaryOneLiner/contentText, token 필드 sourceId/date/summaryType, `dynamic: false`
- `notices_vector` (Vector Search): `contentEmbedding` 1024차원 dotProduct, `indexingMethod: "flat"`, filter 필드 sourceId/date/summaryType

질의는 `$rankFusion`(프로덕션 클러스터 동작 확인, 2026-07-29)으로 text/vector 결합 — **파이프라인 빌더는 skkuverse-ai 소유**. 규칙 (adr-003):

- 6.5k 규모는 `$vectorSearch`에 `exact: true` (ENN) — numCandidates 튜닝 불필요
- 필터(sourceId/date범위/summaryType/isDeleted)는 두 서브파이프라인에 동일 적용 — 사후 필터는 순위를 깨뜨림
- 결과 프로젝션에서 `contentEmbedding` 제외

## 평가 체계 (eval) — skkuverse-ai 소유

30문항 한국어 평가 셋 + hit@k/MRR 하네스. 모델 확정(adr-002 게이트, 후보 5종: Voyage/KURE/BGE-M3/OpenAI/Gemini)·가중치·청킹 판단이 전부 이 위에서 결정된다. 상세는 `skkuverse-ai/docs/internal/search-mcp-plan.md`.

## 소비자별 사용 방식

| 소비자 | 질의 임베딩 | 파이프라인 |
|--------|------------|-----------|
| MCP 서버 (skkuverse-ai 내) | in-process (`/api/embed` 로직 직접) | ai 레포 빌더 — 벤더 장애 시 text-only 폴백 |
| 앱 서버 (NestJS) | ai `POST /api/embed` (`inputType: "query"`) — 벤더 SDK 불필요 | search.json 사본 기반 TS 재구현, 기존 regex 검색 단계적 대체 |
| eval (skkuverse-ai) | 양쪽 방식 모두 | 변형 비교용 |

챗봇 RAG는 이 검색 레이어 위에 후속 (별도 설계).

## 비용·용량 (2026-07-29 실측 기준)

- notices 6,501건 / dataSize 158MB / 압축 storage 94MB. 벡터 추가 +~27MB (BinData), embeddingInput 저장 시 +수십 MB (선택).
- Voyage 백필 ~13M 토큰 — 무료 한도(모델당 200M) 내. 질의 포함 수년치 무료.
- **Atlas 티어 재점검 대상**: M10+오토스케일링을 강제한 건 auto-embed였고 기각됨(adr-001). 일반 Search+Vector Search는 M0에서도 동작 (인덱스 총 3개 제한 — 필요 2개, 스토리지 512MB — 여유). 단 dedicated→M0 다운그레이드는 신규 클러스터+이전 필요, 티어 변경 시 `$rankFusion`(8.1+) 재확인.
- 정제 로직(`html_cleaner.py`/`hashing.py`) 변경은 전 문서 contentHash 갱신 → **전량 재요약 + 재임베딩 유발**을 인지할 것 (현 규모 무해, 10만 건대에선 비용).
