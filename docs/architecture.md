# Architecture

## Overview

skkuverse-crawler — SKKU 관련 데이터 크롤링 + 콘텐츠 정제 서비스.
모듈형 구조로 다양한 크롤러를 추가할 수 있다.

현재 **notices** 모듈이 구현되어 있으며,
Strategy 패턴으로 게시판 유형별 파서를 분리하고 asyncio.Semaphore로 학과를 병렬 크롤링한다 (학과 목록은 `departments.json` 참조).

## Directory Layout

```
py/src/skkuverse_crawler/
├── __main__.py                 ← 진입점
├── cli.py                      ← Click CLI + APScheduler 스케줄러 (모든 모듈 관리)
│
├── modules/                    ← 모듈 시스템
│   ├── base.py                 ← ModuleConfig + CrawlModule Protocol
│   └── registry.py             ← 전역 모듈 레지스트리
│
├── shared/                     ← 공통 인프라 (전 모듈 공유)
│   ├── config.py               ← 중앙집중 환경 설정 (frozen Config dataclass + 싱글턴)
│   ├── db.py                   ← Motor async MongoDB 싱글턴 (config 기반 DB suffix)
│   ├── logger.py               ← structlog (json/dev 포맷, 시작 시 mode_label 로깅)
│   ├── fetcher.py              ← httpx + retry(3회, exponential backoff)
│   ├── html_cleaner.py         ← 6단계 HTML 정제 파이프라인
│   └── html_to_markdown.py     ← cleanHtml → GFM 마크다운 변환
│
├── notices/                    ← 공지 크롤러 모듈
│   ├── module.py               ← NoticesModule (CrawlModule 구현)
│   ├── cli.py                  ← notices 서브커맨드 (--once, --all, --dept, --pages, --delay)
│   ├── orchestrator.py         ← Semaphore(5) 병렬 실행, gather
│   ├── types.py                ← TypedDict 정의 (전략별 config 타입)
│   ├── models.py               ← dataclass: NoticeListItem, NoticeDetail, Notice
│   ├── normalizer.py           ← build_notice 팩토리
│   ├── dedup.py                ← incremental crawl + upsert + null content 재크롤링
│   ├── constants.py            ← SERVICE_START_DATE 등 상수
│   ├── hashing.py              ← compute_content_hash (SHA256)
│   ├── image_verifier.py       ← 공지 이미지 URL 도달 가능 여부 검증
│   ├── backfill.py             ← cleanHtml/contentText/cleanMarkdown 재생성
│   ├── backfill_attachments.py ← skku-standard 첨부 재크롤링
│   ├── backfill_attachment_referer.py ← gnuboard 첨부 referer 백필
│   ├── backfill_wpdm_attachments.py   ← cheme WPDM 첨부 URL 교체
│   ├── attachment_validator.py ← 첨부파일 메타데이터 검증 (URL/name/referer/HTTP)
│   ├── markdown_validator.py   ← cleanMarkdown 렌더링 품질 검증
│   ├── update_checker.py       ← Tier-2 변경 감지 (contentHash 비교)
│   ├── parser.py               ← BeautifulSoup4 래퍼 (load_html, extract_text, extract_attr)
│   ├── config/
│   │   ├── loader.py           ← departments.json 로드 + 셀렉터 검증
│   │   └── departments.json    ← 학과 설정 (SSOT)
│   └── strategies/
│       ├── base.py             ← CrawlStrategy 추상 베이스
│       ├── skku_standard.py    ← SKKU 표준 게시판 (dl/dt/dd)
│       ├── wordpress_api.py    ← WordPress REST API
│       ├── skkumed_asp.py      ← ASP + EUC-KR 인코딩
│       ├── jsp_dorm.py         ← 기숙사 JSP 게시판
│       ├── custom_php.py       ← 커스텀 PHP 게시판
│       ├── gnuboard.py         ← Gnuboard (table/list 스킨)
│       └── gnuboard_custom.py  ← Gnuboard 커스텀 변형
```

## Execution Modes

| 명령 | 설명 |
|------|------|
| `python -m skkuverse_crawler notices --once` | notices 1회 실행 (incremental) |
| `python -m skkuverse_crawler notices --once --all` | notices 전체 크롤 (non-incremental) |
| `python -m skkuverse_crawler notices --once --dept skku-main --pages 3` | 단일 학과, 최대 3페이지 |
| `python -m skkuverse_crawler update-check` | 최근 14일 공지 변경 감지 (Tier-2) |
| `python -m skkuverse_crawler backfill-content` | cleanHtml/contentText/cleanMarkdown 재생성 (dry-run) |
| `python -m skkuverse_crawler backfill-content --apply` | 실제 업데이트 |
| `python -m skkuverse_crawler backfill-attachment-referer --apply` | gnuboard 첨부 referer 백필 |
| `python -m skkuverse_crawler backfill-attachments --apply` | skku-standard 첨부 재크롤링 |
| `python -m skkuverse_crawler backfill-wpdm-attachments --apply` | cheme WPDM 첨부 URL 교체 |
| `python -m skkuverse_crawler validate-attachments` | 첨부파일 메타데이터 검증 |
| `python -m skkuverse_crawler validate-markdown` | cleanMarkdown 렌더링 품질 검증 |
| `python -m skkuverse_crawler summarize` | AI 요약 1회 실행 |
| `python -m skkuverse_crawler start` | 전체 스케줄러 (모든 모듈 cron/interval) |
| `python -m skkuverse_crawler start --module notices` | 단일 모듈만 스케줄링 |

## Data Flow

```
cli.py (Click CLI / APScheduler)
  → loader.load_and_validate() → list[DepartmentConfig] (셀렉터 검증 + 중복 ID 체크)
  → orchestrator.run_crawl(departments, options)
    → Semaphore(5) × crawl_department()
      → 1. find_null_content() → list[DetailRef] → 이전 실패 글 상세 재크롤링
      → 2. crawl_list(page) → list[NoticeListItem]
      → 3. find_existing_meta() + should_continue() → incremental 판단
      → 4. crawl_detail(ref: DetailRef) → NoticeDetail | None
      → 5. build_notice(list_item, detail, config) → Notice
          → clean_html() → cleanHtml
          → _text_from_clean_html() → contentText
          → html_to_markdown() → cleanMarkdown
          → compute_content_hash() → contentHash
          → verify_notice_images() (이미지 URL 검증)
      → 6. upsert_notice() / update_with_history() → inserted | updated | touched
    → DeptResult (성공/실패/소요시간)
  → Summary logging
  → close_client()

[update-check 모드]
  → update_checker.run_update_check(departments)
    → 최근 N일 공지 조회 → 상세 재fetch → contentHash 비교 → 변경분 업데이트
```

## Key Design Decisions

### Centralized Config (`shared/config.py`)

skkuverse-server의 `lib/config.js` 패턴을 Python으로 포팅한 중앙집중 환경 설정 모듈.

**구조:**
- `CrawlerEnv` enum (`production`, `development`, `test`) + frozen `Config` dataclass
- `init_config()` — 싱글턴 초기화. 내부에서 `load_dotenv(override=False)` 호출하여 시스템 환경변수(Docker ENV 등)가 `.env` 파일보다 우선
- `get_config()` — 캐시된 싱글턴 반환 (미초기화 시 lazy init)
- `reset_config()` — 테스트용 싱글턴 초기화

**환경별 동작:**

| `CRAWLER_ENV` | DB 이름 | mode_label |
|---------------|---------|------------|
| `production` | `skku_notices` | `PRODUCTION (prod DB)` |
| `development` | `skku_notices_dev` | `DEVELOPMENT (dev DB)` |
| `test` | `skku_notices_test` | `TEST` |

**설계 원칙:**
- 모든 `os.getenv()` 호출을 config.py에 집중 — db.py, logger.py 등은 `get_config()`만 호출
- `CRAWLER_ENV` 값은 `.lower()` 정규화하여 case-insensitive (`TEST`, `Development` 등 모두 허용)
- 비-test 모드에서 `MONGO_URL` 누락 시 `SystemExit`으로 즉시 종료 (fail-fast)
- `load_dotenv(override=False)` — 이미 설정된 시스템 환경변수를 덮어쓰지 않음. Docker 환경에서 `CRAWLER_ENV=production`을 ENV로 넘기면 `.env`의 `CRAWLER_ENV=development`보다 우선

**초기화 흐름:**
```
CLI entrypoint (cli.py / notices/cli.py)
  → init_config()
    → load_dotenv(override=False)   # .env 로드 (시스템 ENV 우선)
    → load_config()                 # os.environ → Config dataclass
    → validate (MONGO_URL 필수)     # 누락 시 SystemExit
    → 싱글턴 캐시
  → configure_logging()             # config에서 env, log_format 읽기
  → mode_label 로깅                 # "DEVELOPMENT (dev DB)" 등
```

### Module Structure
- `shared/` — config, DB, logger, fetcher 등 모든 모듈이 공유하는 인프라
- `notices/` — 공지 크롤러 모듈. 자체 types, config, strategies 보유
- 향후 모듈 추가 시 같은 패턴으로 독립 모듈 생성
- 각 모듈은 `CrawlModule` Protocol 구현, `cli.py`에서 APScheduler로 스케줄링

### Strategy Pattern
- `CrawlStrategy` 추상 베이스: `crawl_list()` + `crawl_detail(ref: DetailRef)`
- `DetailRef = { article_no, detail_path }` — URL 패턴이 다른 사이트 지원
- departments.json에서 strategy 이름으로 매핑
- selectors를 config에 두어 같은 전략이라도 학과별 DOM 차이를 JSON 변경으로 대응

### Incremental Crawl + Smart Change Detection
- 1페이지 목록은 항상 fetch하되, DB의 기존 메타(title, date)와 비교
- **변경된 글만** 상세 fetch + upsert
- **변경 없는 글**: `bulk_touch_notices()`로 views + crawled_at만 갱신
- 모든 article_no가 DB에 있으면 → early stop

### Error Handling
| 상황 | 처리 |
|------|------|
| 목록 fetch 실패 (5xx/timeout) | retry 3회 → 실패 시 해당 학과 skip |
| 상세 1건 fetch 실패 | content: None으로 저장, 나머지 계속 진행 |
| 파싱 에러 | 해당 글 skip, 경고 로깅 |
| content: None인 기존 글 | 다음 사이클에서 상세 재크롤링 시도 |

## MongoDB

- DB: `skku_notices` (dev: `skku_notices_dev`, test: `skku_notices_test`)
- Collection: `notices`
- Unique compound index: `{ articleNo: 1, sourceDeptId: 1 }`
- Upsert: `update_one({ articleNo, sourceDeptId }, { "$set": doc }, upsert=True)`

## Environment

모든 환경변수는 `shared/config.py`에서 중앙 관리. 직접 `os.getenv()` 호출 금지.

| 변수 | 필수 | 기본값 | 설명 |
|------|------|--------|------|
| `MONGO_URL` | Yes (비-test) | — | MongoDB 연결 문자열 |
| `MONGO_DB_NAME` | No | `skku_notices` | DB 이름 (환경별 suffix 자동 추가) |
| `CRAWLER_ENV` | No | `production` | `development` → `_dev`, `test` → `_test`, `production` → suffix 없음. case-insensitive |
| `LOG_FORMAT` | No | `json` | `json` (구조화 로그) / `dev` (컬러 콘솔) |
