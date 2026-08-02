# ADR-007: Atlas Automated Embedding 채택 (adr-001 대체)

- **상태**: 채택됨 (2026-08-01)
- **대체하는 결정**: [adr-001 (직접 임베딩)](adr-001-direct-embedding.md) — 해당 ADR 은 "대체됨"으로 갱신
- **관련**: [adr-002 (임베딩 모델)](adr-002-embedding-model.md), [adr-003 (하이브리드 검색)](adr-003-hybrid-search-atlas.md), [search-architecture.md](../search-architecture.md)
- **근거 실험**: `skkuverse-ai/docs/internal/autoembed-verification.md` (2026-08-01, prod 클러스터 실측)

## 맥락

adr-001 은 2026-07-29 에 auto-embed 를 기각하고 직접 임베딩을 택했다. 그 뒤 세 가지가 바뀌었다.

**1. 기각 근거 1번이 반증됐다.** adr-001 은 *"auto-embed 가 만든 벡터는 `__mdb_internal_search` 에 저장되어 애플리케이션이 읽거나 내보낼 수 없다 — 문서 A 의 벡터로 문서 B 를 찾는 기능이 원천 불가능"* 이라고 적었다. 실측 결과 **전반부는 맞고 후반부는 틀렸다.** 내부 컬렉션의 `_id` 가 원본 문서 `_id` 와 동일해 조인이 되고, 꺼낸 BSON int8 벡터를 `queryVector` 로 넣으면 doc↔doc 유사도가 그대로 동작한다.

**2. 직접 임베딩의 운영 비용이 문서보다 훨씬 컸다.** adr-001 은 되돌리기 비용을 *"6,500건 재임베딩 = 수 분"* 으로 적었으나, Voyage 무료 티어(결제수단 미등록)는 **3 RPM / 10K TPM** 이라 6,714건 백필에 **약 9시간**이 걸린다. 매시간 도는 stale 재임베딩도 같은 한도에 걸려 `40 * * * *` 크론과 구조적으로 충돌한다. auto-embed 는 Atlas 가 자체 자격증명으로 호출하므로 이 한도와 무관하다 (50건을 30초에 임베딩).

**3. 하이브리드 검색 호환성이 확인됐다.** 문서에 명시가 없어 auto-embed 채택의 최대 불확실성이었던 항목 — `$rankFusion` 서브파이프라인 안에서 `query.text` 가 동작하는지 — 를 실측으로 확인했다. **동작한다.** adr-003 의 하이브리드 설계를 유지할 수 있다.

## 결정

**Atlas Automated Embedding 채택.** 크롤러는 벡터를 만들지도 저장하지도 않는다.

크롤러가 하는 일은 **문서당 텍스트 필드 하나(`embeddingInput`)를 구성해 저장하는 것**뿐이다. 임베딩·재임베딩·동기화는 Atlas 가 담당한다.

```
[크롤러]  embeddingInput 조합 + $set        ← 문자열 연결. API 호출 없음
[Atlas ]  autoEmbed 인덱스가 자동 임베딩·동기화
[질의  ]  $vectorSearch { query: {text}, model } 또는 $rankFusion 서브파이프라인
```

## 근거

1. **삭제되는 것이 많다** — `notices_embedding/ai_client.py`, 벡터 `$set`, `contentEmbedding`/`embeddingModel`/`embeddingAt`/`embeddingFailures` 필드, 9시간짜리 백필, 임베딩 벤더 키 관리, 모델 정합성 방어(`search.json` 의 모델 pin 배포). skkuverse-ai 의 `/api/embed`(Phase A1) 도 통째로 불필요해진다.
2. **속도 제한 문제가 사라진다** — Voyage 무료 티어 3 RPM 이 백필과 stale 재임베딩을 모두 막고 있었다. 결제수단 등록으로 풀 수 있으나, auto-embed 는 그 결정 자체를 불필요하게 만든다.
3. **모델 드리프트가 구조적으로 불가능해진다** — 색인 모델과 질의 모델이 **같은 인덱스 정의 하나**에서 나온다. 세 소비자(크롤러·MCP·앱 서버)가 각자 모델을 지정할 여지가 없다. adr-001 시절 4중 방어를 설계했던 문제가 소멸한다.
4. **doc↔doc 유사도가 가능하다** (위 맥락 1). 다만 비공식 경로다 — 아래 "감수하는 것" 참조.

## 감수하는 것

1. **`find_similar_notices` 가 비문서화 내부 네임스페이스에 의존한다.** 컬렉션명이 `<인덱스UUID>-<해시>-1-0` 형태라 런타임 조회가 필요하고, 인덱스 재생성 시 바뀌며, MongoDB 가 구조를 바꿔도 breaking change 로 취급되지 않는다.
   → **완화**: 주 기능(`search_notices`)은 공식 경로만 쓴다. 내부 구조가 깨져도 검색은 안 죽고 유사도 도구만 멈춘다.
2. **MCP 서버 권한이 넓어진다.** `read@skku_notices` 로는 `__mdb_internal_search` 가 안 보인다. adr-004 의 3중 read-only 방어 중 "DB 유저 스코프" 층이 약해진다.
   → **완화**: 유사도 기능을 별도 커넥션/유저로 분리하거나, 기능 자체를 후순위로 미룬다.
3. **임베딩 입력 조합 규칙만 우리 것이고 나머지는 Atlas 것이다.** `output_dimension`·`input_type`·truncation 동작을 우리가 통제하지 못한다. 특히 **Voyage 의 문서/질의 비대칭 임베딩(`input_type`)을 Atlas 가 적용하는지 확인할 수 없다.**
4. **모델 선택지가 4종으로 고정** — `voyage-4-lite` / `voyage-4` / `voyage-4-large` / `voyage-code-3`. KURE-v1·BGE-M3 같은 한국어 특화 모델로 갈아탈 길이 막힌다. (adr-002 는 2종 실측으로 Voyage 를 확정했으므로 당장은 무관)
5. **양자화가 int8(`scalar`)** — 실측 확인값. 명시적으로 선언해 기본값 변경에 흔들리지 않게 한다.

## 대안과 기각 사유

- **직접 임베딩 유지** (adr-001): 통제권은 최대지만 A1 + Phase 2b 전체를 구현해야 하고, 무료 티어 3 RPM 문제를 결제수단 등록으로 따로 풀어야 한다. 얻는 통제권(모델 자유·float32·공식 API 만 사용)의 값어치가 그 비용보다 작다고 판단. 기각.
- **auto-embed + 유사도용 벡터만 직접**: 같은 텍스트를 두 번 임베딩하는 낭비 + "어느 게 진짜냐" 이원화. adr-001 이 이미 같은 이유로 기각했고 그 판단은 여전히 유효. 기각.
- **Atlas 독립 Embedding API (`ai.mongodb.com/v1/embeddings`)**: 벡터를 우리가 소유하면서 과금·키만 Atlas 로 통합하는 절충안. 다만 직접 임베딩의 구현량이 그대로 남고, 문서상 속도 티어도 *"payment history and spending 기준"* 이라 즉시 개선이 보장되지 않는다. 기각.

## 되돌리기 비용

**낮다.** 원본 텍스트(`contentText`·`summary` 등)가 DB 에 그대로 있고 `embeddingInput` 도 문서 필드로 남으므로, 직접 임베딩으로 돌아가려면 인덱스 정의를 `vector` 타입으로 바꾸고 백필을 한 번 돌리면 된다. 크롤러 코드 변경은 `notices_embedding` 모듈 추가 하나다.

## 재검토 조건

- 내부 네임스페이스 구조가 바뀌어 `find_similar_notices` 가 깨질 때 → 유사도 기능만 직접 임베딩으로 분리하거나 기능 철회
- Atlas 가 `input_type` 비대칭을 적용하지 않는 것이 확인되고 그로 인한 품질 저하가 측정될 때
- 한국어 특화 모델(KURE-v1·BGE-M3)이 자체 평가에서 Voyage 대비 유의미하게 우위로 확인될 때 → 모델 선택 자유가 필요하므로 직접 임베딩 복귀
