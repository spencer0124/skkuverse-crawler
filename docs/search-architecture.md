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

레포 루트, `sources.json`과 같은 방식으로 `py/scripts/generate_artifacts.py`가 검증 + `py/generated/`에 산출. 소비자(server·ai 2곳)는 push가 아니라 **pull**로 받는다 — `skkuverse/contracts/manifest.json`에 계약을 등록하면 `skkuverse_sync.py pull`이 해시 락과 함께 사본을 갱신한다. 담는 것:

```jsonc
{
  "embedding": {
    "model": "voyage-4-large",     // autoEmbed 인덱스 정의에 그대로 들어감 (adr-002)
    "quantization": "scalar",      // int8. 실측 확인값 — 기본값에 의존하지 않고 명시
    "inputVersion": 1              // compose_embedding_input 조합 규칙 버전
  },
  "indexes": { "search": "notices_search", "vector": "notices_vector" },
  "hybrid": { "weights": { "text": 1.0, "vector": 1.0 }, "pipelineLimit": 50 }  // 게이트 B에서 확정
}
```

> **adr-007 이후 빠진 것**: `documentModel`/`queryModel` 이원화(autoEmbed 는 모델 하나), `dimensions`(Atlas 가 모델에 맞춰 결정), `similarity`(마찬가지). 남은 `model` 은 **소비자가 호출에 쓰는 값이 아니라 인덱스를 만들 때 쓰는 값**이다 — 질의 측은 `$vectorSearch` 에 `model` 을 넘기지만 인덱스 정의와 호환되는 값이어야 하므로 사본으로 전달한다.

모델명은 env로 오버라이드하지 않는다 — 어긋나면 에러 없이 검색 품질만 조용히 무너지는 유형의 설정이므로, 변경 경로를 search.json 수정 + codegen 재실행 하나로 고정.

## ② 임베딩 입력 필드 (notices 컬렉션에 추가 예정)

adr-007 이후 크롤러가 저장하는 것은 **텍스트 한 필드뿐**이다. 벡터·모델·임베딩 시각은 Atlas 내부 DB 소관이라 문서에 남지 않는다.

| 필드 | 타입 | 설명 |
|------|------|------|
| `embeddingInput` | string | `autoEmbed` 인덱스가 임베딩할 텍스트. **이 필드가 곧 인덱스의 `path`** |
| `embeddingInputVersion` | int | 조합 규칙 버전. 규칙 변경 시 재조합 대상 판별 |
| `embeddingInputHash` | string | 조합 당시의 `contentHash` — 재조합 판정 |
| `embeddingInputAt` | datetime | 조합 시각 |

> ~~`contentEmbedding` / `embeddingModel` / `embeddingContentHash` / `embeddingAt` / `embeddingFailures`~~ — adr-007 로 전부 불필요. 특히 **`embeddingFailures` 가 사라지는 게 크다**: API 호출이 없으니 실패할 것이 없다(문자열 연결은 실패하지 않는다).

**입력 조합 v1** (`compose_embedding_input`): `title + category + summaryOneLiner + summary + contentText`, 16,000자 캡. 조합 규칙 변경 시 `inputVersion` 올림.

> 캡 16,000자의 근거: `voyage-4-large` 요청당 120K 토큰 한도에서 도출. 참고로 **모델 비교 실측은 8,000자로 잘라서 쟀다** — OpenAI 가 입력당 8,191 토큰 한도라 공정 비교를 위해 맞춘 것이고(영향 0.9%), Voyage 확정으로 그 제약은 사라졌다.

**재조합 판정** — 세 경로 (`plugins/ai_summary` predicate 관용구 미러):

1. 본문 수정: `embeddingInputHash != contentHash`
2. 요약이 나중에 붙음: `summaryAt > embeddingInputAt` (크롤 `*/30`, 요약 `:20` — 크롤 직후엔 요약 없이 조합될 수 있다)
3. 조합 규칙 변경: `embeddingInputVersion != 현재 inputVersion`

⚠️ **`aiSummaryAt` 을 절대 기록하지 않는다** — 서버 FCM 디스패치 게이트라 기록 시 스퓨리어스 푸시 발생. (`plugins/ai_summary/processor.py` 의 주석과 동일한 규칙)

> 실패 가드(`embeddingFailures {"$not": {"$gte": 3}}`)는 불필요하다 — 호출이 없어 실패 카운터가 의미를 잃는다.

## ③ 인덱스 + 하이브리드 파이프라인

인덱스 정의는 별도 JSON 파일 없이 `py/scripts/manage_search_indexes.py`(예정, 이 레포 — 컬렉션 소유자·readWrite 크리덴셜)가 search.json에서 **코드로 구성**:

- `notices_search` (Atlas Search): `lucene.nori`, string 필드 title/summary/summaryOneLiner/contentText, token 필드 sourceId/date/summaryType, `dynamic: false`
- `notices_vector` (Vector Search, **autoEmbed**):
  ```json
  { "fields": [
      { "type": "autoEmbed", "modality": "text", "path": "embeddingInput",
        "model": "voyage-4-large", "quantization": "scalar" },
      { "type": "filter", "path": "sourceId" },
      { "type": "filter", "path": "date" },
      { "type": "filter", "path": "summaryType" },
      { "type": "filter", "path": "isDeleted" } ] }
  ```

`create_search_index()` 는 설치된 pymongo 4.16 / Motor 3.7 에 이미 있다 — 의존성 추가 불필요. (계획서에 있던 `motor 3.7.x` 번프 사유였던 `Binary.from_vector` 는 벡터를 직접 만들지 않게 되어 무의미해졌다.)

질의는 `$rankFusion`으로 text/vector 결합 — **파이프라인 빌더는 skkuverse-ai 소유**. 프로덕션 클러스터(MongoDB 8.0.29) 동작 확인 2026-07-29, auto-embed 서브파이프라인 포함 재확인 2026-08-01. 규칙 (adr-003):

- 1만 건 미만 규모는 `$vectorSearch`에 `exact: true` (ENN) — numCandidates 튜닝 불필요
- 필터(sourceId/date범위/summaryType/isDeleted)는 두 서브파이프라인에 동일 적용 — 사후 필터는 순위를 깨뜨림
- ~~결과 프로젝션에서 `contentEmbedding` 제외~~ → 벡터가 문서에 없으므로 불필요
- ⚠️ **결과 dedup 이 필수** — 코퍼스의 67%가 제목 중복 그룹(최대 32부)이라 접지 않으면 `limit: 10` 에 같은 공지 사본이 10건 나간다. 정책은 정규화 제목 기준(공백 제거 + casefold). 상세·근거는 `skkuverse-ai/eval/results.md`

## 평가 체계 (eval) — skkuverse-ai 소유

한국어 평가 셋 **26문항**(6버킷) + 마감일 전용 4문항 + hit@k/MRR 하네스. 모델 확정(adr-002 게이트 A, **2026-08-01 완료**)·가중치(게이트 B, 미완)·청킹 판단이 전부 이 위에서 결정된다. 상세는 `skkuverse-ai/docs/internal/search-mcp-plan.md`, 수치는 `skkuverse-ai/eval/results.md`.

## 소비자별 사용 방식

adr-007 이후 **세 소비자 모두 질의 임베딩을 하지 않는다** — 텍스트를 그대로 `$vectorSearch` 에 넘긴다.

| 소비자 | 질의 방식 | 파이프라인 |
|--------|----------|-----------|
| MCP 서버 (skkuverse-ai 내) | `$vectorSearch { query: {text}, model }` | ai 레포 빌더 — Atlas 임베딩 장애 시 text-only 폴백 |
| 앱 서버 (NestJS) | 동일 — **벤더 SDK·임베딩 API 호출 모두 불필요** | search.json 사본 기반 TS 재구현, 기존 regex 검색 단계적 대체 |
| eval (skkuverse-ai) | 오프라인 비교는 벤더 API 직접 호출(캐시), Atlas 변형은 `query.text` | 변형 비교용 |

챗봇 RAG는 이 검색 레이어 위에 후속 (별도 설계). RAG 관점에서는 hit@1 보다 **recall@10** 이 중요하다 — top N 을 LLM 에 넘기므로 1위가 정답일 필요가 없고 N 안에 들어왔는지가 전부다.

## 비용·용량

> 코퍼스 건수는 크롤 주기마다 변한다. 아래는 **2026-08-01 측정치**이고, 최신값은 `skkuverse-ai/eval/results.md`(재실행마다 갱신)를 볼 것.

- notices **6,714건** / dataSize 158MB / 압축 storage 94MB. **벡터는 Atlas 내부 DB 에 저장되어 우리 컬렉션 용량에 잡히지 않는다.** `embeddingInput` 텍스트 저장분만 +수 MB.
- 임베딩 비용은 **Atlas 조직으로 과금** — `voyage-4-large` $0.12/1M 토큰, 색인 시점과 질의 시점 양쪽. 백필 ~13M 토큰. Voyage 무료 200M 한도가 Atlas 경로에도 적용되는지는 **미확인**.
- **Voyage 무료 티어 3 RPM / 10K TPM 제약이 사라졌다** — auto-embed 는 Atlas 자체 자격증명으로 호출한다 (50건을 30초에 임베딩, 실측).
- **Atlas 티어**: M10+ 에서 auto-embed 를 쓰려면 스토리지·티어 오토스케일링이 강제되지만, 2026-08-01 실측에서 이 클러스터는 인덱스 생성이 그대로 수락됐다. 티어 변경 시 ~~`$rankFusion`(8.1+)~~ → **`$rankFusion` 은 8.0 도입 기능**이라 현 클러스터(8.0.29)에서 동작한다. 재확인이 필요한 것은 오토스케일링 조건 쪽이다.
- 정제 로직(`html_cleaner.py`/`hashing.py`) 변경은 전 문서 contentHash 갱신 → **전량 재요약 + `embeddingInput` 재조합 → Atlas 전량 재임베딩** 유발을 인지할 것 (재임베딩 비용이 이제 Atlas 과금으로 잡힌다).
