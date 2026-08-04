# Architecture

## Overview

skkuverse-crawler — SKKU 관련 데이터 크롤링 + 콘텐츠 정제 서비스.
모듈형 구조로 다양한 크롤러를 추가할 수 있다.

현재 **notices** 모듈이 구현되어 있으며,
Strategy 패턴으로 게시판 유형별 파서를 분리하고 asyncio.Semaphore로 학과를 병렬 크롤링한다 (학과 목록은 `sources.json` 참조).

## Directory Layout

세 층 + 조립 리프. 층 사이의 화살표는 한 방향뿐이다 — `core/`는 아무것도 모르고, `modules/`는 `core/`만 알고, `plugins/`가 바깥 세계에 붙는다. 조립은 `wiring.py`와 CLI 리프에서만 일어난다 (adr-006 결정 ①).

```
py/src/skkuverse_crawler/
├── __init__.py                 ← iter_notices 지연 재수출 (PEP 562) + __version__
├── __main__.py                 ← 진입점
├── cli.py                      ← Click 루트 그룹. 서브커맨드 지연 로딩 (--help가 motor를 안 부름)
├── env.py                      ← os.environ·dotenv 유일 접점. settings_from_env()
├── wiring.py                   ← 조립 루트. plugins를 import하는 유일한 비-CLI 파일
│                                 build_runtime(settings, profile) + 부팅 거부(ProfileError)
│
├── core/                       ← 인프라 0. env 읽기 없음, SystemExit 없음, stdlib만
│   ├── __init__.py             ← 공개 API 재수출 (__all__)
│   ├── ports.py                ← Sink / SeenIndex / WorkSeed / Notifier Protocol + Null 객체
│   ├── events.py               ← 이벤트 어휘 2계층 (결과 = 동결, 진행 = minor 확장 가능)
│   ├── crawl.py                ← CrawlMode = Incremental(seen) | FullSweep (합 타입)
│   ├── runner.py               ← run_events: 이벤트 → sink, 집계 표를 코드로
│   ├── results.py              ← SourceResult (소스 단위 결과)
│   ├── sinks.py                ← JsonLinesSink — 코어 유일의 구체 sink
│   ├── pipeline.py             ← ContentDoc / Stage / Pipeline (모양만; 구체 스테이지는 modules)
│   ├── testing.py              ← assert_sink_contract — 서드파티에 출하되는 적합성 스위트
│   ├── module.py               ← ModuleConfig + CrawlModule Protocol
│   ├── registry.py             ← 전역 모듈 레지스트리
│   ├── settings.py             ← frozen Config dataclass (환경 접근 없음)
│   └── sources.py              ← SourceConfigError (라이브러리는 sys.exit 하지 않는다)
│
├── modules/notices/            ← 공지가 무엇이고 어떻게 크롤하는가
│   ├── module.py               ← NoticesModule (CrawlModule 구현)
│   ├── cli.py                  ← notices 서브커맨드 (--once, --all, --source, --pages, --json)
│   ├── simple.py               ← iter_notices() facade — 이벤트 스트림의 필터
│   ├── orchestrator.py         ← run_crawl(Semaphore 5) + iter_source(이벤트 제너레이터)
│   ├── policy.py               ← 순수 술어: has_changed, should_continue, page_below_floor
│   ├── stages.py               ← 구체 콘텐츠 스테이지 + DEFAULT_PIPELINE
│   ├── normalizer.py           ← build_notice 팩토리
│   ├── validation.py           ← 첨부·마크다운 순수 검사 (DB 없이 테스트 가능)
│   ├── models.py               ← dataclass: NoticeListItem, NoticeDetail, Notice
│   ├── types.py                ← TypedDict 정의 (전략별 config 타입)
│   ├── constants.py            ← SERVICE_START_DATE
│   ├── hashing.py              ← compute_content_hash (SHA256)
│   ├── image_verifier.py       ← 이미지 dimension 측정 (HTTP Range 32KB)
│   ├── parser.py               ← BeautifulSoup4 래퍼
│   ├── config/                 ← loader.py (sources.json 로드 + 셀렉터 검증) + 패키지 사본
│   └── strategies/             ← CrawlStrategy 9종 + STRATEGY_MAP 레지스트리
│
├── plugins/                    ← 바깥 세계에 붙는 어댑터. 전부 optional extra
│   ├── mongo/                  ← seen.py · sink.py · work_seed.py (3 포트 구현)
│   │                             update_checker.py (Tier-2) · audit.py (검증 DB 스캔) · cli.py
│   ├── health/                 ← logic.py(순수 판정) · store.py · module.py(09:00 요약) · cli.py
│   ├── discord/webhook.py      ← Notifier 구현 (config 게이트, never-raise)
│   ├── ai_summary/             ← processor.py · query.py · ai_client.py · module.py · cli.py
│   ├── dispatch/client.py      ← FCM 디스패치 핑 (ai_summary를 통해서만 도달)
│   └── scheduler/runner.py     ← APScheduler 어댑터
│
└── shared/                     ← 아직 층에 배정되지 않은 공통 코드 (해체 예정)
    ├── db.py                   ← Motor async MongoDB 싱글턴 (MongoUrlMissing)
    ├── logger.py               ← structlog (json/dev 포맷)
    ├── fetcher.py              ← httpx + retry(3회, exponential backoff)
    ├── html_cleaner.py         ← 6단계 HTML 정제 파이프라인
    └── html_to_markdown.py     ← cleanHtml → GFM 마크다운 변환
```

경계는 관례가 아니라 테스트로 강제된다 (`py/tests/structure/`): `modules/`가 `plugins/`를 import하면 AST 스캔이 실패하고, `import skkuverse_crawler.core`가 드라이버나 서드파티 패키지를 끌어오면 실패한다.

`shared/`의 최종 배치(`fetcher`→core, `html_*`→core, `db`→plugins/mongo)는 [core-plugin-architecture.md](core-plugin-architecture.md) §레이아웃 참조 — 이 리팩터에서 하지 않은 것이다.

## Execution Modes

`--help`가 뱉는 7개 서브커맨드가 전부다. 일회성 `backfill-*` 커맨드들은 소멸했다 — null content 재크롤은 `WorkSeed` 포트 + `ContentRefreshed` 이벤트로 크롤 경로에 흡수됐고, 나머지 첨부 백필은 일회성 마이그레이션이라 유지할 이유가 없었다.

| 명령 | 필요 extra | 설명 |
|------|-----------|------|
| `notices --once` | mongo | notices 1회 실행 (incremental) |
| `notices --once --all` | mongo | 전체 크롤 (FullSweep) |
| `notices --once --source skku-main --pages 3` | mongo | 단일 학과, 최대 3페이지 |
| `notices --source skku-main --pages 1 --json` | — | stdout JSON Lines, 저장소 없음. 코어 전용 설치의 인수 조건 |
| `update-check` | mongo | 최근 14일 공지 변경 감지 (Tier-2) |
| `validate-attachments` | mongo | 첨부파일 메타데이터 검증 |
| `validate-markdown` | mongo | cleanMarkdown 렌더링 품질 검증 |
| `repair-dimensions` | mongo | tier-2가 지운 이미지 차원 복구. `--apply` 없이는 읽기만. 멱등 |
| `summarize` | mongo, ai | AI 요약 1회 실행 |
| `health-summary` | mongo, discord | 크롤 헬스 일일 요약 1회 발송 |
| `start` | mongo, sched | 전체 스케줄러 (모든 모듈 cron) |
| `start --module notices` | mongo, sched | 단일 모듈만 스케줄링 |

extra가 없으면 해당 커맨드는 설치 방법을 알려주고 종료한다. `--help` 자체는 아무것도 import하지 않는다 (지연 그룹).

## Data Flow

크롤은 **이벤트를 만드는 쪽**과 **그걸로 뭔가 하는 쪽**으로 갈려 있다. `iter_source`는 저장소를 모르고 카운터도 세지 않는다; `run_events`가 sink에 흘리고 집계한다. 그래서 저장소 없이 크롤하는 것(`--json`, `iter_notices`)이 특수 경로가 아니라 sink를 바꾼 것뿐이다.

```
cli.py → wiring.notices_ports()          ← plugins 조립은 여기서만
  → loader.load_and_validate() → list[dict] (셀렉터 검증 + 중복 ID 체크)
  → orchestrator.run_crawl(departments, options, ports=, mode=)
    → crawl_coverage 로그 (attempted vs enabled — known-issues §7 재발 감지)
    → sink.prepare(SourceSpec) × 소스
    → Semaphore(5) × _crawl_department()
      → run_events(iter_source(...), sink, result=SourceResult)

          iter_source가 yield 하는 것 (저장소 무지):
            SourceStarted
            work_seed.pending_refs() → 상세 재크롤 → ContentRefreshed   ← 백필, mode 무관
            반복 { crawl_list(page) → list[NoticeListItem]
                   mode=Incremental이면 seen.lookup() → should_continue() 판정
                   crawl_detail() → NoticeDetail
                   build_notice() ∘ DEFAULT_PIPELINE
                     NormalizeUrls → CleanHtml → VerifyImages → InjectImageDimensions
                     → SizeGuard(5MB) → ExtractText → ToMarkdown → ContentHash
                   → NoticeCrawled | NoticeUnchanged | ItemSkipped | ItemFailed
                   PageCompleted }
            SourceFinished(stopped_by=…)

          run_events가 하는 것:
            모든 이벤트 → sink.accept()  (미지의 이벤트도 균일하게)
            NoticeCrawled → accept 반환 Outcome이 inserted/updated 결정
            PageCompleted → sink.flush()   ← 예외는 전파, 소스 결과 탈락
            SourceFinished → source_down / last_error / duration_ms
    → list[SourceResult] → record_and_alert 훅 (wiring이 설치)
  → close_client()

[update-check 모드]
  → plugins/mongo/update_checker.run_update_check(departments)
    → 최근 N일 공지 조회 → 상세 재fetch → contentHash 비교 → 변경분 업데이트
```

## Key Design Decisions

### Centralized Config (`env.py` + `core/settings.py`)

설정은 **값**과 **환경 읽기**로 갈려 있다: 값 타입은 `core/settings.py`(환경도 파일시스템도 건드리지 않는 frozen dataclass — 라이브러리 호출자가 `Config` 리터럴을 만들고 env를 통째로 건너뛸 수 있는 이유), 환경 읽기는 `env.py`(`os.environ`·dotenv 유일 접점, `test_env_is_the_only_environment_reader`가 AST로 강제). 진입점은 `settings_from_env()`.

**`MONGO_URL` 필수 검증은 설정 로딩에서 제거됐다.** extras 도입으로 "저장소 없음"이 정당한 상태가 됐기 때문이고, 그게 `notices --json`과 `iter_notices()`를 가능하게 한 변화다. 요구 자체가 사라진 건 아니라 두 곳으로 **이동**했다 — `shared.db.get_client()`의 `MongoUrlMissing`, 그리고 production 프로파일 부팅 게이트 `wiring.ProfileError`. 설정 로딩이 배포 정책을 강제하지 않게 된 것이 요점이다.

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
    → settings_from_env()           # os.environ → Config dataclass (env.py)
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
- sources.json에서 strategy 이름으로 매핑
- selectors를 config에 두어 같은 전략이라도 학과별 DOM 차이를 JSON 변경으로 대응

### Incremental Crawl + Smart Change Detection
- 1페이지 목록은 항상 fetch하되, DB의 기존 메타(title, date)와 비교
- **변경된 글만** 상세 fetch + upsert
- **변경 없는 글**: `bulk_touch_notices()`로 views + crawled_at만 갱신
- 페이지의 모든 **일반 글**이 DB에 있으면 → all-known early stop (`should_continue()`)
- 페이지의 **일반 글**이 전부 `SERVICE_START_DATE` 이전이면 → floor stop (`_page_below_floor()`)
- 상단 고정(`공지`) 행은 모든 페이지에 반복 노출되므로 두 판정 모두에서 제외 — skku-standard 파서가 첫 info 셀("공지" vs "No.###")로 `pinned` 플래그를 세움. 고정글은 페이지 0에서 항상 처리되므로 누락 없음

### Error Handling
| 상황 | 처리 |
|------|------|
| 목록 fetch 실패 (5xx/timeout) | retry 3회 → 실패 시 해당 학과 skip |
| 상세 1건 fetch 실패 | content: None으로 저장, 나머지 계속 진행 |
| 파싱 에러 | 해당 글 skip, 경고 로깅 |
| content: None인 기존 글 | 다음 사이클에서 상세 재크롤링 시도 |

### Crawl Health (관측/알림)

- `plugins/health/` — 소스 단위 헬스 추적. 알림은 `core.ports.Notifier` 경유이지 Discord 직접 의존이 아니다 (`plugins/discord/webhook.py`가 그 구현)
- 신호: `DeptResult.source_down` — **page 0 list fetch 실패**만 다운으로 간주 (부분 에러 제외)
- L1: `record_and_alert()` — `crawl_health` 컬렉션(sourceId당 1건)에 연속 실패 카운트 저장, 연속 3틱 도달 시 틱당 1개 배치 메시지로 알림, 회복 시 recovered 알림. `alerted` 래치로 중복 발화 방지. 순수 판정은 `plugins/health/logic.py::decide_transitions` (DB 无 유닛테스트 가능). `NoticesModule`이 이 함수를 직접 부르지 않고 **wiring이 설치하는 훅**으로 받는다 — modules가 plugins를 import하지 않는다는 불변식 때문
- L2: `crawl-health-summary` 모듈 — 매일 09:00 KST 요약 (활성/실패 소스, 최근 24h 신규 건수는 `_id` ObjectId 타임스탬프 범위로 계산)
- 알림 실패는 절대 크롤을 중단시키지 않음 (never-raise, `dispatch_client.py`와 동일 계약)

## MongoDB

- DB: `skku_notices` (dev: `skku_notices_dev`, test: `skku_notices_test`)
- Collection: `notices`, `crawl_health`
- Unique compound index: `{ articleNo: 1, sourceId: 1 }`
- Upsert: `update_one({ articleNo, sourceId }, { "$set": doc }, upsert=True)`

## Environment

모든 환경변수는 `env.py`에서 중앙 관리. 직접 `os.getenv()` 호출 금지 (예외는 `modules/notices/config/loader.py`의 `SOURCES_JSON_PATH` 하나 — 경로 해석이 Config 생성보다 먼저다).

| 변수 | 필수 | 기본값 | 설명 |
|------|------|--------|------|
| `MONGO_URL` | Yes (비-test) | — | MongoDB 연결 문자열 |
| `MONGO_DB_NAME` | No | `skku_notices` | DB 이름 (환경별 suffix 자동 추가) |
| `CRAWLER_ENV` | No | `production` | `development` → `_dev`, `test` → `_test`, `production` → suffix 없음. case-insensitive |
| `LOG_FORMAT` | No | `json` | `json` (구조화 로그) / `dev` (컬러 콘솔) |
