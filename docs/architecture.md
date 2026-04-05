# Architecture

## Overview

skkuverse-crawler — SKKU 관련 데이터 크롤링 + 콘텐츠 정제 서비스.
모듈형 구조로 notices, meals, library 등 다양한 크롤러를 추가할 수 있다.

현재 **notices** 모듈이 구현되어 있으며, Strategy 패턴으로 게시판 유형별 파서를 분리하고
p-limit으로 133개 학과를 병렬 크롤링한다.

## Directory Layout

```
src/
├── index.ts                    ← 전체 cron 스케줄러 (모든 모듈 관리)
│
├── shared/                     ← 공통 인프라 (전 모듈 공유)
│   ├── db.ts                   ← MongoDB 싱글턴 (lazy init, maxPoolSize:5)
│   ├── logger.ts               ← pino (dev: pino-pretty, test: silent)
│   └── fetcher.ts              ← axios + retry(3회, exponential backoff) + rate-limit
│
└── notices/                    ← 공지 크롤러 모듈
    ├── index.ts                ← barrel export (공개 API)
    ├── cli.ts                  ← 모듈별 직접 실행 진입점 (CLI + cron)
    ├── orchestrator.ts         ← p-limit(5) 병렬 실행, Promise.allSettled
    ├── types.ts                ← DepartmentConfig, CrawlStrategy, DetailRef, PaginationConfig
    ├���─ normalizer.ts           ← Notice 인터페이스 + buildNotice 팩토리
    ├── dedup.ts                ← incremental crawl + upsert + null content 재크롤링
    ├── parser.ts               ← cheerio 래퍼 (loadHtml, extractText, extractAttr)
    ├── cleanHtml.ts            ← 6단계 HTML 정제 파이프라인
    ├── config/
    │   ├── loader.ts           ← departments.json 로드 + 셀렉터 검증
    │   └── departments.json    ← 133개 학과 설정
    └── strategies/
        ├── skku-standard.ts    ← SKKU 표준 게시판 (dl/dt/dd)
        ├��─ wordpress-api.ts    ← WordPress REST API
        ├── skkumed-asp.ts      ← ASP + EUC-KR ���코딩
        ├── jsp-dorm.ts         ← 기숙사 JSP 게시판
        ├── custom-php.ts       ← 커스텀 PHP 게시판
        ├── gnuboard.ts         ← Gnuboard (table/list 스킨)
        └── gnuboard-custom.ts  ← Gnuboard 커스텀 변형

scripts/
├── backfill-cleanhtml.ts       ← cleanHtml 필드 백필
├── test-cleanhtml.ts           ← HTML 정제 파이프라인 테스트
└── verify-selectors.ts         ← CSS 셀렉터 검증 스크립트
```

## Execution Modes

| 명령 | 설명 |
|------|------|
| `npx tsx src/notices/cli.ts --once` | notices 1회 실행 (incremental) |
| `npx tsx src/notices/cli.ts --once --all` | notices 전체 크롤 (non-incremental) |
| `npx tsx src/notices/cli.ts --once --dept skku-main --pages 3` | 단일 학과, 최대 3페이지 |
| `npx tsx src/notices/cli.ts` | notices cron 모드 (30분 간격) |
| `npx tsx src/index.ts` | 전체 스케줄러 (모든 모듈 cron) |

## Data Flow

```
cli.ts (CLI args / cron)
  → loader.loadAndValidate() → DepartmentConfig[] (셀렉터 검증 + 중복 ID 체크)
  → orchestrator.runCrawl(departments, options)
    → p-limit(5) × crawlDepartment()
      → 1. findNullContent() → DetailRef[] → 이전 실패 글 상세 재크롤링
      → 2. crawlList(page) → NoticeListItem[]
      → 3. findExistingMeta() + shouldContinue() → incremental 판단
      → 4. crawlDetail(ref: DetailRef) → NoticeDetail | null
      → 5. buildNotice(listItem, detail, config) → Notice
      → 6. upsertNotice() → inserted | updated
    → DeptResult (성공/실패/소요시간)
  → Summary logging
  → closeClient()
```

## Key Design Decisions

### Module Structure
- `shared/` — DB, logger, fetcher 등 모든 모듈이 공유하는 인프라
- `notices/` — 공지 크롤러 모듈. 자체 types, config, strategies 보유
- 향후 `meals/`, `library/` 등 추가 시 같은 패턴으로 독립 모듈 생성
- 각 모듈은 `cli.ts`로 독립 실행 가능, `src/index.ts`에서 전체 스케줄링

### Strategy Pattern
- `CrawlStrategy` 인터페이스: `crawlList()` + `crawlDetail(ref: DetailRef)`
- `DetailRef = { articleNo, detailPath }` — URL 패턴이 다른 사이트 지원
- departments.json에서 strategy 이름으로 매핑
- selectors를 config에 두어 같은 전략이라도 학과별 DOM 차이를 JSON 변경으로 대응

### Incremental Crawl + Smart Change Detection
- 1페이지 목록은 항상 fetch하되, DB의 기존 메타(title, date)와 비교
- **변경된 글만** 상세 fetch + upsert
- **변경 없는 글**: `bulkTouchNotices()`로 views + crawledAt만 갱신
- 모든 articleNo가 DB에 있으면 → early stop

### Error Handling
| 상황 | 처리 |
|------|------|
| 목록 fetch 실패 (5xx/timeout) | retry 3회 → 실패 시 해당 학과 skip |
| 상세 1건 fetch 실패 | content: null로 저장, 나머지 계속 진행 |
| 파싱 에러 | 해당 글 skip, 경고 로깅 |
| content: null인 기존 글 | 다음 사이클에서 상세 재크롤링 시도 |

## MongoDB

- DB: `skku_notices` (dev: `skku_notices_dev`, test: `skku_notices_test`)
- Collection: `notices`
- Unique compound index: `{ articleNo: 1, sourceDeptId: 1 }`
- Upsert: `updateOne({ articleNo, sourceDeptId }, { $set: doc }, { upsert: true })`

## Environment

| 변수 | 설명 |
|------|------|
| `MONGO_URL` | MongoDB 연결 문자열 |
| `MONGO_DB_NAME` | DB 이름 (기본: `skku_notices`) |
| `NODE_ENV` | `development` → `_dev` suffix, `test` → `_test`, `production` → suffix 없음 |
