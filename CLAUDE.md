# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

SKKU 관련 데이터 크롤링 + 콘텐츠 정제 서비스. Python 구현 (`py/`).

## Commands

```bash
cd py
python -m skkuverse_crawler start                        # 스케줄러 실행
python -m skkuverse_crawler start --module notices       # 단일 모듈
python -m skkuverse_crawler notices --once               # 공지 1회 실행
python -m skkuverse_crawler notices --once --dept skku-main --pages 3
python -m skkuverse_crawler summarize                      # AI 요약 1회 실행 (기본 batch-size: 50)
python -m skkuverse_crawler summarize --batch-size 500     # 초기 backfill
python -m skkuverse_crawler update-check                   # 최근 14일 공지 변경 감지 (Tier-2)
python -m skkuverse_crawler update-check --days 7 --dept skku-main
python -m skkuverse_crawler backfill-content               # cleanHtml/contentText/cleanMarkdown 재생성 (dry-run)
python -m skkuverse_crawler backfill-content --apply       # 실제 업데이트
python -m skkuverse_crawler backfill-content --apply --dept cheme --limit 10  # 샘플링
python -m skkuverse_crawler backfill-attachment-referer              # gnuboard 첨부 referer 추가 (dry-run)
python -m skkuverse_crawler backfill-attachment-referer --apply      # 실제 업데이트
python -m skkuverse_crawler backfill-attachment-referer --apply --dept nano --limit 5
python -m skkuverse_crawler backfill-attachments                     # skku-standard 첨부 재크롤링 (dry-run)
python -m skkuverse_crawler backfill-attachments --apply --dept law --limit 10
python -m skkuverse_crawler backfill-wpdm-attachments                # cheme WPDM 첨부 URL 교체 (dry-run)
python -m skkuverse_crawler backfill-wpdm-attachments --apply
python -m skkuverse_crawler validate-attachments                     # 첨부파일 메타데이터 검증
python -m skkuverse_crawler validate-attachments --dept cheme --no-http --json
python -m skkuverse_crawler validate-markdown                        # cleanMarkdown 렌더링 품질 검증
python -m skkuverse_crawler validate-markdown --dept skku-main --severity error --json

# 테스트 & 린트
python -m pytest tests/ -v                  # 전체 테스트
python -m pytest tests/notices/ -v          # 특정 모듈만
python -m pytest tests/ -k "test_name"      # 단일 테스트
ruff check src/                             # 린트
mypy src/                                   # 타입 체크
```

## Codegen (SSOT)

```bash
cd py
python scripts/generate_artifacts.py    # departments.json + categories.json → 7개 아티팩트 생성 + 형제 레포 복사
```

**생성 아티팩트:**

| 아티팩트 | 출력 위치 | 용도 |
|---------|----------|------|
| `dept_ids.py` | `py/src/.../config/dept_ids.py` | Python DeptId enum |
| `server-departments.json` | `py/generated/` → `skkuverse-server` 복사 | 서버 API 응답용 (noticeAvailable, hasCategory, hasAuthor 포함) |
| `docker-crawl-filter.env` | `py/generated/` | Docker 참고용 |
| `coverage-table.md` | `docs/department-coverage-analysis.md` | 캠퍼스/단과대별 학과 테이블 |
| `departments-by-college.md` | `docs/departments-by-college.md` | 단과대학별 학과 목록 |
| `departments-by-app-category.md` | `docs/departments-by-app-category.md` | 앱 카테고리별 학과 목록 |
| `server-categories.json` | `py/generated/` → `skkuverse-server` 복사 | Server-driven 탭 구성 (탭 순서, 라벨, picker/fixed 모드) |

`py/generated/`는 `.gitignore`에 등록됨.

### 학과 추가/변경 절차

1. `departments.json` (레포 루트) 수정 — campus, college, appCategory, crawlEnabled + 크롤링 설정
2. 새 카테고리 추가 시 `categories.json`도 수정
3. `cd py && python scripts/generate_artifacts.py` 실행
4. 형제 레포(skkuverse-server)에 자동 복사됨 (존재 시)

## Architecture

### 공통 패턴

**모듈형 구조**: `shared/` (config, DB, logger, HTTP 클라이언트) + 각 모듈 디렉토리 (notices, notices_summary)

**Strategy Pattern**: `CrawlStrategy` 인터페이스 + `departments.json` config-driven. 전략 목록은 `departments.json`의 `strategy` 필드 및 `generate_artifacts.py`의 `STRATEGY_FEATURES` 참조.

**SSOT (Single Source of Truth)**: 레포 루트에 두 개의 SSOT 파일:
- `departments.json` — 학과 데이터. 크롤링 설정(strategy, selectors, baseUrl) + 메타데이터(campus, college, appCategory, crawlEnabled).
- `categories.json` — 앱 탭/카테고리 구성. 탭 순서(배열 순서), 라벨(ko/en), 탭 모드(picker: 학과 선택 / fixed: 단일 학과 고정). picker 탭은 `appCategory == category.id`인 학과를 자동 수집.

`py/scripts/generate_artifacts.py`가 두 파일을 읽어 서버/Docker/문서용 파생 파일을 자동 생성. 양방향 검증(departments↔categories 정합성)도 포함.

- `campus`: 유효값은 `generate_artifacts.py`의 `VALID_CAMPUSES` 참조.
- `appCategory`: 유효값은 `categories.json`의 id 목록에서 자동 도출 (+ `null` 허용).
- `crawlEnabled`: 프로덕션 크롤링 여부. `CRAWL_DEPT_FILTER` env var 미설정 시 이 필드가 기본 필터.
- `CRAWL_DEPT_FILTER`: dev/디버깅용 오버라이드로만 사용. 설정하면 crawlEnabled 무시하고 해당 ID만 크롤링.
- `hasCategory`/`hasAuthor`: departments.json에 저장하지 않음. strategy에서 결정론적 도출 (codegen의 STRATEGY_FEATURES 룩업).

**Incremental Crawl**: title+date 변경 감지 → 변경분만 상세 fetch. 페이지 내 전부 DB에 존재하면 early-stop. content:null 기사 자동 재크롤링.

**HTML Cleaning**: 6단계 파이프라인 (`shared/html_cleaner.py`). BS4 junk 제거(WPDM `div.w3eden` 다운로드 블록 포함) + `data:` URI 이미지 제거 + Naver SmartEditor 레이아웃 테이블 unwrap → semantic 정규화(`font-weight: bold|bolder|≥600` → `<strong>`) + underline용 `<em>/<i>` unwrap → URL 절대경로 → nh3 태그/스타일 필터링 → 빈 요소 제거 → 구조 정리(빈 `<span>` unwrap / 단독자식 `<div>` 체인 축약 / `data:` URI 이미지 재거름 / 구두점 전용 inline 제거 / 단독자식 bold unwrap / 인접 inline 병합).

**Markdown 변환**: `shared/html_to_markdown.py`. cleanHtml을 입력으로 받아 markdownify + 전처리(박스 테이블 unwrap, 첫 행 all-bold → `<thead><th>` 승격, `<td>` 내부 `<p>/<div>` flatten)로 GFM을 생성 → `cleanMarkdown` 필드에 저장. `content`/`cleanHtml`/`contentText`는 그대로 유지. 이미지에 width/height 속성이 있으면 `{WxH}` 포맷으로 alt text 앞에 prepend: `![{800x600} 포스터](url)`. width만 있으면 `{w800}`, height만 있으면 `{h600}`. 앱에서 `!\[\{(\d+)x(\d+)\}` 정규식으로 파싱.

**이미지 검증**: `notices/image_verifier.py`. 크롤링 시 `<img>` URL마다 HTTP Range 헤더로 첫 32KB만 요청 → `imagesize` 라이브러리로 dimension 파싱. Range 미지원 서버는 Content-Length ≤ 5MB일 때 전체 응답 사용, 초과 시 스킵. 감지된 dimension은 `normalizer._inject_image_dimensions()`이 cleanHtml의 `<img>` 태그에 `width`/`height` 속성으로 주입.

**contentText 추출**: `normalizer._text_from_clean_html()`. 블록 요소(`<tr>`, `<p>`, `<div>`, `<h1-4>`, `<li>`, `<br>`)가 개행을 만들고 `<td>/<th>`는 공백으로 구분(기존 동작). 셀 내부 `<br>`은 행 구분과 충돌하므로 공백으로 대체.

**WPDM 첨부 추출**: `wordpress-api` 전략(cheme 전용). WPDM 플러그인은 `div.w3eden` 컨테이너 안에 `data-downloadurl` 속성으로 실제 다운로드 URL(`?wpdmdl={id}`)을 제공. 일시적 `refresh` 토큰은 제거하고 저장. 랜딩 페이지 URL(`/download/{slug}/`)은 첨부로 잡지 않음. 파일명은 `h3.package-title a` 텍스트에서 추출. `_extract_attachments()`는 반드시 `clean_html()` 이전에 raw HTML 대상으로 실행해야 함 — `div.w3eden`이 Stage 1에서 제거되므로.

**첨부파일 Referer**: gnuboard 계열 학과(nano, bio-undergrad, bio-grad, pharm)의 `download.php`는 PHP 세션 + Referer 헤더를 검증. 크롤러가 attachment 메타데이터에 `referer` (상세 페이지 URL)를 저장하여 서버 프록시가 세션 수립 후 다운로드할 수 있도록 지원. gnuboard-custom(nano)은 케이스 A(아무 페이지 세션 OK), gnuboard 표준(pharm, bio)은 케이스 B(상세 페이지 방문 필수). bio는 https 미지원(http only).

**첨부파일 검증**: `notices/attachment_validator.py`. URL scheme·host 허용 여부, name 품질, gnuboard referer 존재, 중복 URL, HTTP 도달성(HEAD 요청)을 검사. CLI로 `validate-attachments` 실행. `--no-http`으로 네트워크 체크 스킵, `--json`으로 기계 판독 가능 출력.

**Markdown 검증**: `notices/markdown_validator.py`. cleanMarkdown 필드의 렌더링 품질을 검사. broken emphasis(닫히지 않은 `*`/`**`), 빈 링크, 이미지 dimension 포맷(`{WxH}`), 과도한 빈 줄 등을 감지. severity는 `error`/`warning` 두 단계. CLI로 `validate-markdown` 실행.

### 모듈 시스템 (`py/src/skkuverse_crawler/`)

- `modules/base.py` — `ModuleConfig` (name, collection_name, cron_schedule 또는 interval_seconds) + `CrawlModule` Protocol
- `modules/registry.py` — 전역 모듈 레지스트리
- `cli.py` — APScheduler로 모듈 스케줄링. CronTrigger(notices). `max_instances=1` + `coalesce=True`
- `shared/config.py` — 중앙집중 환경 설정. frozen `Config` dataclass 싱글턴. `init_config()` → `load_dotenv(override=False)` + validation + 캐시. 모든 `os.getenv()` 호출이 여기에 집중됨
- `shared/db.py` — Motor async MongoDB 싱글턴. `get_config().mongo_db_name`으로 환경별 DB 라우팅

### 스케줄 주기

| 모듈 | 타입 | 주기 |
|------|------|------|
| notices | CronTrigger | `*/30 * * * *` (30분) |
| notices-update-check | CronTrigger | `10 8,14,20 * * *` (하루 3회) |
| notices-summary | CronTrigger | `20 * * * *` (매시 20분) |

### DB 이름 규칙

`shared/config.py`의 `_db_name()` 함수에서 환경별 suffix 자동 추가:

`CRAWLER_ENV=production` → `skku_notices` (suffix 없음), `development` → `skku_notices_dev`, `test` → `skku_notices_test`.

`CRAWLER_ENV` 값은 case-insensitive (`TEST`, `Development` 등 허용).

## Environment

`shared/config.py`에서 중앙 관리. `.env` 파일 (`py/.env`) 또는 시스템 환경변수로 설정. `load_dotenv(override=False)` 사용하므로 시스템 ENV가 `.env`보다 우선 (Docker 배포 시 안전).

- `MONGO_URL` — MongoDB 연결 문자열 (필수, 비-test 모드에서 누락 시 SystemExit)
- `MONGO_DB_NAME` — 기본: `skku_notices`
- `CRAWLER_ENV` — `production` / `development` / `test` (case-insensitive)
- `LOG_FORMAT` — `json` (기본) / `dev` (컬러 콘솔)
- `AI_SERVICE_URL` — AI 요약 서비스 URL. 환경별 자동 결정: `production` → `http://ai:4000`, `development`/`test` → `http://127.0.0.1:4000`. 직접 지정 시 우선
- `CRAWL_DEPT_FILTER` — 콤마 구분 학과 ID 필터 (e.g. `skku-main,law`). **dev 오버라이드 전용**. 미설정 시 `departments.json`의 `crawlEnabled: true` 항목만 크롤링


## Testing

Python 테스트는 `py/tests/`에 위치. `respx`로 httpx 요청 목킹, `conftest.py`에서 MongoDB를 autouse fixture로 전역 목킹. `asyncio_mode = "auto"` 설정으로 async 테스트 자동 처리.

`conftest.py`의 `_test_env_and_config` autouse fixture가 매 테스트마다 `reset_config()` + `CRAWLER_ENV=test` 설정. `_mock_db`는 이 fixture에 명시적으로 의존하여 실행 순서 보장.

## Adding New Modules

1. `py/src/skkuverse_crawler/<module>/` 생성 (module.py, fetcher.py 등)
2. `CrawlModule` Protocol 구현 (run, shutdown, config)
3. `cli.py`의 `_start_scheduler()`에 `registry.register()` 추가
4. `shared/` 인프라 재사용 (config, db, logger, fetcher)
