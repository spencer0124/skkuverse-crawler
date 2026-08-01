# ADR-003: 하이브리드 검색 — Atlas Search(nori) + Vector Search + $rankFusion

- **상태**: 채택됨 (2026-07-29) / **수정 (2026-08-01)** — 아래 개정 블록
- **관련**: [adr-007 (auto-embed)](adr-007-atlas-auto-embedding.md), [adr-002](adr-002-embedding-model.md), [search-architecture.md](../search-architecture.md), ~~[adr-001](adr-001-direct-embedding.md)~~(대체됨)

> [!IMPORTANT]
> ## 개정 (2026-08-01) — prod 클러스터 실측 반영
>
> 결정(인덱스 2종 + `$rankFusion`)은 유지된다. 아래 다섯 가지가 바뀐다.
>
> **1. `notices_vector` 가 `autoEmbed` 인덱스가 된다** ([adr-007](adr-007-atlas-auto-embedding.md)).
> `contentEmbedding` 필드는 존재하지 않고, 임베딩 대상은 크롤러가 조합해 저장하는
> `embeddingInput` 텍스트 필드다.
> ```json
> { "fields": [
>     { "type": "autoEmbed", "modality": "text", "path": "embeddingInput",
>       "model": "voyage-4-large", "quantization": "scalar" },
>     { "type": "filter", "path": "sourceId" },
>     { "type": "filter", "path": "date" },
>     { "type": "filter", "path": "summaryType" },
>     { "type": "filter", "path": "isDeleted" } ] }
> ```
> 질의는 `queryVector` 대신 `query: {text: "..."}` + `model` 을 넘긴다. `$rankFusion`
> 서브파이프라인 안에서 동작하는 것을 **실측 확인**했다.
>
> **2. 근거 1번의 버전 추론이 틀렸다.** prod 클러스터는 **MongoDB 8.0.29** 인데
> `$rankFusion` 이 동작한다. 공식 레퍼런스도 *"introduced in MongoDB 8.0"* 이다.
> "8.1+ GA" 는 잘못된 추론이었고, 이 오류가 `search-architecture.md`·`search-mcp-plan.md` 의
> 티어 변경 가드로 전파돼 있다.
>
> **3. `$scoreFusion` 은 이 클러스터에서 미지원** — `Unrecognized pipeline stage name`.
> `$rankFusion` 의 형제 스테이지지만 선택지가 아니다. 아래 "대안과 기각 사유"에 편입.
>
> **4. `$rerank` 는 MongoDB 8.3+ 필요** — 현재 `$rerank is not allowed`. 재검토 조건의
> "rerank-2.5 2단계 추가"는 **클러스터 업그레이드가 선행 조건**이다. Voyage API 직접 호출
> 또는 Atlas 독립 API(`ai.mongodb.com/v1`)로 애플리케이션 레이어에서 우회는 가능하다.
>
> **5. ⚠️ `date` 사전식 범위 필터가 깨져 있다.** 아래 근거 6번은 `date` 가 전부
> `"YYYY-MM-DD"` 라고 전제하는데, 실측상 **829건(12.6%)이 `"2026-07-29 16:18"` 형태**이고
> 1건은 빈 문자열이다. 하한(`$gte`)은 무해하지만 **상한(`$lte "2026-07-29"`)이
> `"2026-07-29 16:18"` 을 제외**해 범위의 마지막 하루가 통째로 누락된다.
> **크롤러 측 정규화가 이 필터의 선행 조건**이다.

## 맥락

현행 공지 검색은 regex substring 매칭(서버 `notices.search.ts`)뿐이다. 자연어 검색·챗봇·MCP가 요구하는 품질을 위해 전문(full-text) 검색과 벡터 검색을 결합해야 한다. Atlas 유료 플랜을 이미 사용 중이므로 Atlas 내장 기능을 최대 활용한다는 방침(사용자 결정) 하에 구성을 확정한다.

## 결정

`notices` 컬렉션에 인덱스 2종 + `$rankFusion` 결합:

1. **Atlas Search 인덱스** (`notices_search`): 한국어 분석기 `lucene.nori`, string 필드 `title`/`summary`/`summaryOneLiner`/`contentText`, 필터용 token 필드 `sourceId`/`date`/`summaryType`, `dynamic: false`
2. **Vector Search 인덱스** (`notices_vector`): ~~`contentEmbedding` (1024차원, `dotProduct`, `indexingMethod: "flat"`)~~ → **`autoEmbed` 타입, `embeddingInput` 경로, `voyage-4-large`** (개정 블록 1번), filter 필드 `sourceId`/`date`/`summaryType`/`isDeleted`
3. **하이브리드 결합**: `$rankFusion` (RRF: `Σ w/(60+rank)`) — text/vector 두 서브파이프라인, 가중치는 `search.json` SSOT에서 관리, Phase 3 실측으로 확정

## 근거 (2026-07-29 검증 사실)

- **$rankFusion은 프로덕션 클러스터에서 이미 동작 확인** — 실제 read-only 쿼리로 실행 성공. ~~(= MongoDB 8.1+ GA)~~ → **정정: 클러스터는 8.0.29 이고 `$rankFusion` 은 8.0 도입 기능이다** (개정 블록 2번). 별도 업그레이드·수동 RRF 폴백 불필요.
- **`lucene.nori`는 전 티어 제공** — 형태소 분석·복합어 분해가 한국어 substring regex의 근본 한계(형태소 경계 미인식)를 해소. 단, Atlas는 nori 세부 옵션(decompound 모드, 사용자 사전)을 노출하지 않음 — 기본값 고정.
- **6,501건 규모는 ENN(`exact: true`) 스위트스팟** — MongoDB 공식 가이드가 1만 건 미만엔 ENN 권장. numCandidates 튜닝 없이 항상 정확한 결과.
- **`dotProduct` 선택 근거**: Voyage 임베딩은 L2-normalized 출력이라 cosine과 순위 동일 + 계산이 더 저렴 (Voyage FAQ 명시).
- **벡터 저장은 BSON BinData float32** (`Binary.from_vector`, pymongo≥4.10): 문서당 ~4.1KB, 총 ~27MB — plain double array(~86MB) 대비 1/3. MongoDB 공식 권장.
- **필터 일관성 규칙**: `sourceId`/`date`/`summaryType` 필터는 **두 인덱스 모두에 선언**하고 **두 서브파이프라인에 동일 적용**해야 함 ($rankFusion 사후 필터는 순위를 깨뜨림). date는 "YYYY-MM-DD" 문자열의 사전순 비교로 범위 필터 동작.

## 대안과 기각 사유

- **Mongo `$text` 인덱스**: 한국어 토크나이저 없음 — substring 대비 이득 없음. 기각.
- **regex 유지 + 벡터만 추가**: 정확 키워드 매칭(학과명·과목코드)에서 형태소 검색의 이점 포기. nori가 그 역할을 상위 호환. 기각.
- **수동 RRF ($unionWith)**: $rankFusion 미지원 버전용 폴백이었으나 클러스터 지원 확인으로 불필요. 기각.
- **외부 검색엔진 (Elasticsearch/Meilisearch 등)**: 운영 컴포넌트 추가 + Atlas 기능 최대 활용 방침에 반함. 기각.

## 재검토 조건

- 문서 수가 수만 건대로 성장해 ENN 지연이 체감될 때 → `numCandidates` 기반 ANN 전환 (인덱스는 그대로)
- nori 기본 decompound가 특정 질의 유형에서 문제를 일으킬 때 → `lucene.cjk` 비교를 eval로
- 정확도 요구가 더 높아질 때 → `rerank-2.5` 2단계 추가 (Phase 밖 옵션)
