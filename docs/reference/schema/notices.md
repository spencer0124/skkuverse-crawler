---
title: notices 컬렉션 스키마
type: reference
status: accepted
owner: zoyoong124@gmail.com
last-updated: 2026-07-24
audience: internal
---

# notices 컬렉션 스키마

> `skku_notices.notices` MongoDB 컬렉션의 canonical 스키마. **필드 정의의 SSOT는 코드**이며, 이 문서는 코드를 가리킨다. 소비자(서버/앱) 관점의 데이터 계약은 [notices-data-contract.md](../notices-data-contract.md), 시스템 전체의 소유권 지도는 [umbrella data-topology](https://github.com/spencer0124/skkuverse/blob/main/docs/architecture/data-topology.md).

## 스키마는 두 파일에 나뉘어 있다

`notices` 문서는 **두 writer가 필드를 나눠 소유**한다 ([근거 ADR](https://github.com/spencer0124/skkuverse/blob/main/docs/decisions/0001-notice-data-ownership.md)):

| 필드 그룹 | writer | SSOT 코드 |
| --- | --- | --- |
| 크롤러 원문 필드 | crawler | `notices/models.py` `Notice` dataclass |
| AI 요약 write-back 필드 (`summary*`) | notices_summary 모듈 (AI 응답으로 `$set`) | `notices_summary/processor.py::run_summary_batch` |

즉 `models.py`에는 `summary*` 필드가 없다 — 요약 필드는 요약 프로세서만 쓴다.

## 크롤러 원문 필드

`notices/models.py`의 `Notice` dataclass가 SSOT (camelCase로 저장). 대표 필드:

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `articleNo` | `int` | 게시글 번호 (SKKU 원본, 학과 내에서만 unique) |
| `title` / `category` / `author` / `department` | `str` | 제목/카테고리/작성자/학과 (전략별로 빈 문자열 가능) |
| `date` | `str` | 작성일 `YYYY-MM-DD` |
| `views` | `int` | 조회수 (전략별 0 가능) |
| `content` / `cleanHtml` / `cleanMarkdown` / `contentText` | `str \| None` | 본문 4종 (아래) |
| `attachments` | `list[dict]` | `[{name, url, ...}]` (gnuboard 계열은 `referer` 포함) |
| `sourceUrl` / `detailPath` | `str` | 원본 상세 URL / 내부 재크롤 경로 |
| `sourceId` | `str` | `sources.json`의 `id` (예: `skku-main`) |
| `crawledAt` | `datetime` | 마지막 크롤링 시각 (UTC) |
| `contentHash` | `str \| None` | `cleanHtml` SHA256 (null = 컨텐츠 없음). 재요약 트리거의 기준 |
| `editHistory` / `editCount` | `list[dict]` / `int` | 최근 수정 이력 / 수정 횟수 |
| `isDeleted` | `bool` | soft delete (원본 사라짐) |
| `consecutiveFailures` | `int` | 상세 fetch 실패 연속 카운트 |
| `lastModified` | `str \| None` | **예약 필드 — 현재 미사용** (파싱 미구현) |

> 전체·최신 목록은 반드시 `notices/models.py`를 본다 (라인번호 박제 금지).

## AI 요약 write-back 필드 (`summary*`)

`notices_summary/processor.py`가 AI 응답을 받아 같은 문서에 `$set`한다. 성공 시 추가되는 필드: `summary`, `summaryOneLiner`, `summaryType`, `summaryPeriods`, `summaryLocations`, `summaryDetails`, `summaryModel`, `summaryAt`, `summaryContentHash`, `summaryFailures`. 각 필드의 의미·형태와 AI 쪽 생성 로직은 [notices-data-contract.md §요약 필드](../notices-data-contract.md)와 [skkuverse-ai notice-summarization](https://github.com/spencer0124/skkuverse-ai/blob/main/docs/explanation/notice-summarization.md).

> [!NOTE]
> `summaryAt`(크롤러 "요약됨" 마커/쿼리 게이트)와 예약 `aiSummaryAt`(**서버 FCM 디스패치 게이트**)는 의도적으로 분리돼 있다 — 요약 의미를 바꿔도 푸시가 깨지지 않게. 서버가 읽는 필드이므로 이름을 바꾸지 않는다.

## 인덱스

인덱스 생성은 두 곳에서 idempotent하게 이뤄진다:

| 인덱스 | 정의 위치 | 용도 |
| --- | --- | --- |
| unique `(articleNo, sourceId)` | `notices/dedup.py::ensure_indexes` | 문서 식별 (같은 articleNo라도 sourceId 다르면 별개 문서) |
| `(sourceId, date desc)` | `notices/dedup.py::ensure_indexes` | 학과별 최신순 조회 |
| `idx_summary_pending` `(summaryAt, contentText)` partial | `notices_summary/query.py::ensure_summary_indexes` | 미요약 문서 스캔 (`contentText` 존재 문서만) |

서버는 자기 읽기 인덱스를 별도로 소유한다 (crawler가 만들지 않음) — [server docs](https://github.com/spencer0124/skkuverse-server/tree/main/docs) 참조.

## 본문 필드 4종

| 필드 | 내용 | 용도 |
|---|---|---|
| `content` | 원본 HTML + 절대 URL (태그/클래스/스타일 전부 보존) | 레거시 렌더링. 재가공 시 `clean_html()` 재투입 입력 소스 (idempotent) |
| `cleanHtml` | `content`를 6단계 파이프라인으로 정제 + nh3 화이트리스트 | 안전하게 렌더 가능한 HTML |
| `cleanMarkdown` | `cleanHtml` → markdownify + 전처리로 변환한 GFM | 모바일 앱 마크다운 렌더링 권장 소스 |
| `contentText` | `cleanHtml`에서 블록 경계 개행 보존 추출한 plain text | 검색 / AI 요약 입력 / 미리보기 |

fetch 실패 시 `content`/`cleanHtml`/`cleanMarkdown`이 모두 `None` → 다음 크롤링에서 재시도. `contentText`는 strategy fallback으로 채워질 수 있다.

**크기 특성**: `content`는 원본 HTML이라 학과별 편차가 크고 WP 사이트는 MB 단위도 가능하며, `cleanHtml`/`cleanMarkdown`/`contentText`는 그보다 훨씬 작다. → **리스트 응답에선 `content`/`cleanHtml`/`cleanMarkdown` 제외 권장, 상세 응답에서만 포함.** (정확한 실측치는 시점에 따라 변하므로 박제하지 않는다.)

## Upsert & 재요약 동작

- 크롤은 `articleNo + sourceId` 기준 upsert. 이미 존재하면 관련 필드를 `$set`으로 덮어씀 → 제목/내용 수정이 자동 반영.
- 수정 감지는 `contentHash` 기반: 요약 시점 `summaryContentHash`와 현재 `contentHash`가 다르면 재요약 대상 (`notices_summary`가 처리).
- 파이프라인 개선을 기존 문서에 소급 적용하는 절차 / 일회성 마이그레이션은 [how-to/run-migrations.md](../../how-to/run-migrations.md).

## DB 이름 라우팅

`shared/config.py::_db_name()`이 `CRAWLER_ENV`별 suffix를 붙인다: production → `skku_notices`, development → `skku_notices_dev`, test → `skku_notices_test`. 연결은 `shared/db.py`의 Motor async 싱글턴 (`get_db()`).

## 관련 문서

- [notices-data-contract.md](../notices-data-contract.md) — 소비자용 데이터 계약 (전략별 가용성·샘플 JSON)
- [schedule.md](schedule.md) — 학사일정 컬렉션
- [how-to/run-migrations.md](../../how-to/run-migrations.md) — 일회성 마이그레이션
- [umbrella data-topology](https://github.com/spencer0124/skkuverse/blob/main/docs/architecture/data-topology.md)
