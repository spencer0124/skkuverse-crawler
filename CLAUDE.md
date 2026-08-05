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
python -m skkuverse_crawler notices --once --source skku-main --pages 3
python -m skkuverse_crawler summarize                      # AI 요약 1회 실행 (기본 batch-size: 50)
python -m skkuverse_crawler summarize --batch-size 500     # 초기 backfill
python -m skkuverse_crawler update-check                   # 최근 14일 공지 변경 감지 (Tier-2)
python -m skkuverse_crawler update-check --days 7 --source skku-main
python -m skkuverse_crawler validate-attachments                     # 첨부파일 메타데이터 검증
python -m skkuverse_crawler validate-attachments --source cheme --no-http --json
python -m skkuverse_crawler validate-markdown                        # cleanMarkdown 렌더링 품질 검증
python -m skkuverse_crawler validate-markdown --source skku-main --severity error --json
python -m skkuverse_crawler health-summary                           # 크롤 헬스 일일 요약 1회 발송
python -m skkuverse_crawler bus --once --poller bus-hssc             # bus 1틱 fetch + 출력 (저장 안 함)
python -m skkuverse_crawler bus --once --poller bus-jongro --json
python -m skkuverse_crawler bus --once --poller bus-campus-eta       # 저장소·extra 불필요. 업스트림이 캡처와 같은 모양인지 확인용
python -m skkuverse_crawler repair-dimensions                        # tier-2가 지운 이미지 차원 복구 (dry-run)
python -m skkuverse_crawler repair-dimensions --apply                # 실제 쓰기. 멱등 — 재실행 시 repaired: 0
python -m skkuverse_crawler repair-attachments                       # 깨진 첨부 링크 복구 (dry-run)
python -m skkuverse_crawler repair-attachments --apply               # 실제 쓰기. 멱등
python -m skkuverse_crawler repair-attachments --refetch --apply     # 원본이 삭제한 첨부까지 떨어냄 (공지당 요청 1회)

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
python scripts/generate_artifacts.py    # 세 SSOT 파일 → 8개 아티팩트 (형제 레포에 쓰지 않음)
```

**생성 아티팩트:**

| 아티팩트 | 출력 위치 | 용도 |
|---------|----------|------|
| `source_ids.py` | `py/src/.../modules/notices/config/source_ids.py` | Python SourceId enum |
| `server-sources.json` | `py/generated/` | 서버 API 응답용 (crawlAvailable, excludeReason, hasCategory, hasAuthor 포함) |
| `coverage-table.md` | `docs/department-coverage-analysis.md` | 캠퍼스/단과대별 학과 테이블 |
| `departments-by-college.md` | `docs/departments-by-college.md` | 단과대학별 학과 목록 |
| `departments-by-app-category.md` | `docs/departments-by-app-category.md` | 앱 카테고리별 학과 목록 |
| `server-categories.json` | `py/generated/` | Server-driven 탭 구성 (탭 순서, 라벨, picker/fixed 모드) |
| `server-exclude-reasons.json` | `py/generated/` | excludeReason 키→문구(ko/en) 맵 — 앱 미지원 사유 문구를 server-driven으로 |
| `sources.json` (패키지 사본) | `py/src/.../modules/notices/config/sources.json` | wheel/editable/컨테이너용 런타임 패키지 데이터. SSOT는 레포 루트 — codegen이 바이트 동일 복사, 테스트가 동기화 강제 |

**모든 아티팩트는 커밋된다.** `py/generated/`는 더 이상 gitignore 대상이 아니다 — 소비자 레포가
원격에서 이 파일들을 받아 자기 사본과 해시 비교하기 때문이다. CI의 `codegen` 잡이 재생성 후
`git diff --exit-code`를 돌리므로, SSOT만 고치고 codegen을 안 돌린 PR은 머지되지 않는다.
`EXPECTED_GENERATED` + `assert_no_orphans()`가 폐기 아티팩트 잔존도 막는다
(`server-departments.json`이 gitignore 뒤에서 4개월 살아남은 전례).

`docker-crawl-filter.env`는 삭제됐다. 소비자가 없었고, 내용물인 `CRAWL_SOURCE_FILTER`는
2026-04-21 인시던트의 그 변수다 (`docs/known-issues.md` §7) — 커밋하면 복붙 가능한 장애 페이로드가
레포에 남는다. dev 용도는 `--source a,b`로 충분.

### 학과 추가/변경 절차

1. `sources.json` (레포 루트) 수정 — campus, college, appCategory, crawlEnabled + 크롤링 설정
2. 새 카테고리 추가 시 `categories.json`도 수정
3. `cd py && python scripts/generate_artifacts.py` 실행
4. 생성된 아티팩트를 **이 레포에 커밋** (CI가 codegen == committed 강제)
5. 소비자 레포로 전파: `python3 ../skkuverse/tools/skkuverse_sync.py pull --all`
   — 어느 레포에 커밋이 필요한지 출력해준다. 계약 정의는
   [skkuverse/contracts/manifest.json](https://github.com/spencer0124/skkuverse/blob/main/contracts/manifest.json)

## Architecture

### 공통 패턴

**모듈형 구조** (adr-006 core/plugin 분리, PR 0~9 완료 — 로드맵 종료 2026-08-02): `core/` (포트·이벤트·러너·파이프라인 모양·설정 타입·JsonLinesSink — 인프라 import 금지) + `modules/notices/`·`modules/bus/` (크롤 도메인 로직 — 두 아키타입, adr-008 ①) + `plugins/` (인프라 어댑터: `mongo` 저장·snapshot·update_checker·audit, `health`, `discord`, `ai_summary`, `dispatch`, `scheduler`) + `shared/` (DB, logger, HTTP 클라이언트, HTML 처리) + `env.py` (os.environ·dotenv 유일 접점). 조립은 `wiring.py`가 담당 — `modules/`는 `plugins/`를 import하지 않는다 (AST 테스트로 강제). `plugins/`를 import할 수 있는 건 조립 리프(wiring.py, cli.py들)뿐.

**두 아키타입** (adr-008 ①): **항목 스트림**(notices — 페이지네이션 + `SeenIndex`/`WorkSeed` + 항목별 diff)과 **스냅샷**(bus — 키 하나당 문서 하나를 통째 교체, `plugins/mongo/snapshot.SnapshotSink`). 하나로 일반화하지 않았다. 스냅샷 쪽에 **코어 변경은 없었다** — 플러그인 하나(≈100줄)면 충분했다는 게 둘을 따로 둔 근거다. 새 모듈은 `docs/adding-a-module.md` §0에서 아키타입부터 고른다.

**의존성 extras** (PR 8): `pip install skkuverse-crawler`는 크롤·파싱·정제·CLI만 설치한다. 인프라는 optional — `[mongo]`(motor) / `[sched]`(apscheduler) / `[discord]`·`[ai]`(tenacity) / `[all]`. Dockerfile은 4개 extra를 모두 설치하며, **그 집합이 pyproject와 어긋나면 `test_packaging.py`가 실패한다**. production 프로파일은 필수 플러그인(mongo, sched) 부재 시 `wiring.ProfileError`로 기동 거부. 저장소 없이 돌려보려면 `notices --json` (stdout JSON Lines, 로그는 stderr).

**Strategy Pattern**: `CrawlStrategy` 인터페이스 + `sources.json` config-driven. 전략 목록은 `sources.json`의 `strategy` 필드 및 `generate_artifacts.py`의 `STRATEGY_FEATURES` 참조.

**SSOT (Single Source of Truth)**: 레포 루트에 세 개의 SSOT 파일:
- `sources.json` — 학과 데이터. 크롤링 설정(strategy, selectors, baseUrl) + 메타데이터(campus, college, appCategory, crawlEnabled). 크롤 불가 소스는 `excludeReason`(앱 노출 키) + `excludeNote`(내부 전용 기술 사유, 서버로 안 나감).
- `categories.json` — 앱 탭/카테고리 구성. 탭 순서(배열 순서), 라벨(ko/en), 탭 모드(picker: 학과 선택 / fixed: 단일 학과 고정). picker 탭은 `appCategory == category.id`인 학과를 자동 수집.
- `exclude-reasons.json` — excludeReason 키 + ko/en 문구. `VALID_EXCLUDE_REASONS`가 여기서 도출되고, 키→문구 맵이 서버를 거쳐 앱에 server-driven으로 전달됨 (categories 라벨과 동일 패턴). 새 사유 추가 = 이 파일 수정이 전부 (앱 릴리즈 불필요; 앱 번들 i18n은 구서버 호환 fallback).

`py/scripts/generate_artifacts.py`가 세 파일을 읽어 서버/Docker/문서용 파생 파일을 자동 생성. 양방향 검증(departments↔categories, excludeReason↔exclude-reasons 정합성)도 포함.

- `campus`: 유효값은 `generate_artifacts.py`의 `VALID_CAMPUSES` 참조.
- `appCategory`: 유효값은 `categories.json`의 id 목록에서 자동 도출 (+ `null` 허용).
- `crawlEnabled`: 프로덕션 크롤링 여부. `CRAWL_SOURCE_FILTER` env var 미설정 시 이 필드가 기본 필터.
- `CRAWL_SOURCE_FILTER`: dev/디버깅용 오버라이드 **전용**. ⚠️ **절대 프로덕션 `docker-compose.yml`에 두지 말 것** — 설정 시 `sources.json`의 `crawlEnabled`를 덮어써 나머지 학과가 전부 침묵 차단됨. 컨테이너 Up 상태와 로그 무에러에도 coverage가 급락하므로 외부에서 알아채기 어려움 (2026-04-21 인시던트, `docs/known-issues.md` §7 참조).
- `hasCategory`/`hasAuthor`: sources.json에 저장하지 않음. strategy에서 결정론적 도출 (codegen의 STRATEGY_FEATURES 룩업).

**Incremental Crawl**: title+date 변경 감지 → 변경분만 상세 fetch. 페이지 내 일반 글 전부 DB에 존재하면 early-stop. 상단 고정(공지) 행은 매 페이지 반복 노출되므로 early-stop/floor-stop 판정에서 제외 (`pinned` 플래그, skku-standard 파서가 인식). content:null 기사 자동 재크롤링.

**HTML Cleaning**: 6단계 파이프라인 (`shared/html_cleaner.py`). BS4 junk 제거(WPDM `div.w3eden` 다운로드 블록 포함) + `data:` URI 이미지 제거 + Naver SmartEditor 레이아웃 테이블 unwrap → semantic 정규화(`font-weight: bold|bolder|≥600` → `<strong>`) + underline용 `<em>/<i>` unwrap → URL 절대경로 → nh3 태그/스타일 필터링 → 빈 요소 제거 → 구조 정리(빈 `<span>` unwrap / 단독자식 `<div>` 체인 축약 / `data:` URI 이미지 재거름 / 구두점 전용 inline 제거 / 단독자식 bold unwrap / 인접 inline 병합).

**Markdown 변환**: `shared/html_to_markdown.py`. cleanHtml을 입력으로 받아 markdownify + 전처리(박스 테이블 unwrap, 첫 행 all-bold → `<thead><th>` 승격, `<td>` 내부 `<p>/<div>` flatten)로 GFM을 생성 → `cleanMarkdown` 필드에 저장. `content`/`cleanHtml`/`contentText`는 그대로 유지. 이미지에 width/height 속성이 있으면 `{WxH}` 포맷으로 alt text 앞에 prepend: `![{800x600} 포스터](url)`. width만 있으면 `{w800}`, height만 있으면 `{h600}`. 앱에서 `!\[\{(\d+)x(\d+)\}` 정규식으로 파싱.

**이미지 검증**: `modules/notices/image_verifier.py`. 크롤링 시 `<img>` URL마다 HTTP Range 헤더로 첫 32KB만 요청 → `imagesize` 라이브러리로 dimension 파싱. Range 미지원 서버는 Content-Length ≤ 5MB일 때 전체 응답 사용, 초과 시 스킵. 감지된 dimension은 `normalizer._inject_image_dimensions()`이 cleanHtml의 `<img>` 태그에 `width`/`height` 속성으로 주입. 크롤 경로에서는 `modules/notices/stages.py`의 `VerifyImages`(선택 스테이지) + `InjectImageDimensions`가 이 둘을 수행 — `DEFAULT_PIPELINE.without("verify-images")`로 비활성화 가능.

**contentText 추출**: `normalizer._text_from_clean_html()`. 블록 요소(`<tr>`, `<p>`, `<div>`, `<h1-4>`, `<li>`, `<br>`)가 개행을 만들고 `<td>/<th>`는 공백으로 구분(기존 동작). 셀 내부 `<br>`은 행 구분과 충돌하므로 공백으로 대체.

**WPDM 첨부 추출**: `wordpress-api` 전략(cheme 전용). WPDM 플러그인은 `div.w3eden` 컨테이너 안에 `data-downloadurl` 속성으로 실제 다운로드 URL(`?wpdmdl={id}`)을 제공. 일시적 `refresh` 토큰은 제거하고 저장. 랜딩 페이지 URL(`/download/{slug}/`)은 첨부로 잡지 않음. 파일명은 `h3.package-title a` 텍스트에서 추출. `_extract_attachments()`는 반드시 `clean_html()` 이전에 raw HTML 대상으로 실행해야 함 — `div.w3eden`이 Stage 1에서 제거되므로.

**첨부파일 Referer**: 다운로드 엔드포인트가 Referer를 검증하는 전략들이 attachment 메타데이터에 `referer`(상세 페이지 URL)를 저장한다. 목록의 진실 원천은 `validation.py`의 `REFERER_REQUIRED_STRATEGIES`:
- **gnuboard 계열**(bio-undergrad, bio-grad, pharm, nano)의 `download.php`는 PHP 세션 + Referer 둘 다 검증. gnuboard-custom(nano)은 케이스 A(아무 페이지 세션 OK), gnuboard 표준(pharm, bio)은 케이스 B(상세 페이지 방문 필수). bio는 https 미지원(http only).
- **custom-php**(cal-undergrad, cal-grad)의 NFUpload는 **Referer만** 검증한다(세션 불필요). 그래서 `GNUBOARD_STRATEGIES`와 **별도 상수로 유지**해야 한다 — gnuboard는 세션 게이트라 `validate-attachments`의 HTTP 체크를 스킵하지만 cal은 체크를 받아야 한다. 합치면 cal이 검증 사각지대로 들어간다.

Referer가 없으면 **에러가 아니라 200 + HTML alert 페이지**가 온다 — 소비자에게는 "다운로드는 됐는데 파일이 아닌" 상태. 서버 프록시는 저장된 `referer`가 있을 때만 헤더를 붙이므로 이 필드가 비면 프록시가 할 수 있는 일이 없다 (`docs/known-issues.md` §12).

**첨부파일 검증**: 순수 검사는 `modules/notices/validation.py`, DB 스캔 드라이버는 `plugins/mongo/audit.py`. URL scheme·host 허용 여부, name 품질, referer 존재, 중복 URL, HTTP 도달성을 검사. CLI로 `validate-attachments` 실행. `--no-http`으로 네트워크 체크 스킵, `--json`으로 기계 판독 가능 출력.

도달성 검사는 **HEAD가 아니라 ranged GET**이고, status 외에 **응답 내용까지 판정**한다. 이 도메인의 파손된 다운로드는 404를 주지 않고 200 + `text/html`로 alert 페이지를 주기 때문 — `Content-Type`이 `text/html`인데 `Content-Disposition: attachment`가 없으면 `html_response`로 잡는다. GET인 이유는 하나 더 있다: sls 핸들러는 HEAD에 404/403을 주고 GET에만 정상 응답한다.

**Markdown 검증**: 순수 검사는 `modules/notices/validation.py`, DB 스캔 드라이버는 `plugins/mongo/audit.py`. cleanMarkdown 필드의 렌더링 품질을 검사. broken emphasis(닫히지 않은 `*`/`**`), 빈 링크, 이미지 dimension 포맷(`{WxH}`), 과도한 빈 줄 등을 감지. severity는 `error`/`warning` 두 단계. CLI로 `validate-markdown` 실행.

### 모듈 시스템 (`py/src/skkuverse_crawler/`)

- `core/module.py` — `ModuleConfig` (name, cron_schedule 또는 interval_seconds) + `CrawlModule` Protocol
- `core/registry.py` — 전역 모듈 레지스트리
- `cli.py` — APScheduler로 모듈 스케줄링. CronTrigger(notices). `max_instances=1` + `coalesce=True`
- `env.py` — 환경 접점. `settings_from_env()` + `init_config()`/`get_config()` 싱글턴. `load_dotenv(override=False)`. **`os.environ`을 읽는 곳은 여기와 `modules/notices/config/loader.py`(SOURCES_JSON_PATH) 둘뿐** — AST 테스트로 강제
- `core/settings.py` — frozen `Config` dataclass + `CrawlerEnv` + 순수 파생(db suffix, 기본 AI URL). 환경 접근 없음
- `shared/db.py` — Motor async MongoDB 싱글턴. `get_config().mongo_db_name`으로 환경별 DB 라우팅

### 스케줄 주기

| 모듈 | 가족 | 타입 | 주기 | 틱 관용 |
|------|------|------|------|--------|
| notices | notices | CronTrigger | `*/30 * * * *` (30분) | 기본(10초) |
| notices-update-check | notices | CronTrigger | `10 8,14,20 * * *` (하루 3회) | 기본 |
| notices-summary | notices | CronTrigger | `20 * * * *` (매시 20분) | 기본 |
| crawl-health-summary | notices | CronTrigger | `0 9 * * *` (매일 09:00 KST — 컨테이너 TZ가 KST) | 기본 |
| bus-hssc | bus | IntervalTrigger | 10초 | 30초 |
| bus-jongro | bus | IntervalTrigger | 40초 | 120초 |
| bus-campus-eta | bus-eta | IntervalTrigger | 600초 (부팅 시 1회 선행) | 300초 |

**관용 시간(`misfire_grace_time`)이 주기보다 큰 이유**: 실시간 폴러는 *현재* 상태를 가져오므로
늦은 틱이 오래된 틱은 아니다. 막아야 할 건 쌓임뿐이고 그건 `max_instances=1` + `coalesce=True`가
이미 한다. 반대로 스케줄러 기본값(10초)을 10초 폴러에 그대로 쓰면 이벤트 루프가 바쁠 때마다
틱이 통째로 버려진다 — misfire는 coalesce보다 **먼저** 판정되기 때문. 버려진 틱은
`job_tick_missed` 경고로 남는다.

### bus 모듈 (adr-008)

bus는 `skkuverse-server`의 `ROLE=poller` 컨테이너에서 이관 중이다. **현재 단계에서는
`__shadow` 접미사가 붙은 키에만 쓴다** — 서버가 아직 진짜 키를 쓰고 있고, 한 `_id`에
writer가 둘이면 나중에 쓴 쪽이 이긴다. 커트오버는 `wiring.BUS_SHADOW_WRITES`를 `False`로
바꾸는 커밋 하나이며, 서버가 해당 키 쓰기를 멈춘 뒤여야 한다.

| 모듈 | 컬렉션 | 문서 `_id` |
|------|--------|-----------|
| bus-hssc | `bus_cache` (서버 소유, `_updatedAt` TTL 60초) | `hssc__shadow` |
| bus-jongro | `bus_cache` | `jongro_{stations,locations}_{02,07}__shadow` |
| bus-campus-eta | `campus_eta` (크롤러 소유, **TTL 없음**) | `campus_eta__shadow` |

campus ETA만 컬렉션이 다른 이유: `bus_cache`의 TTL은 60초인데 이 모듈의 주기는 600초라
`bus_cache`에 두면 10분 중 9분은 문서가 없다. 서버가 이 키를 `bus_cache`에서 읽은 적이
없어(온디맨드 계산) 계약이 아직 없었고, 없을 때만 공짜인 선택을 한 것이다.

문서 모양은 서버의 `BusCacheService.write`와 같다 — 페이로드는 `data` 아래 중첩되고,
그 위에 모듈이 찍는 `fetchedAt`(업스트림이 응답한 시각)과 sink가 찍는 `_updatedAt`(쓴 시각)이 붙는다.

### DB 이름 규칙

`core/settings.py`의 `db_name_for()` 함수에서 환경별 suffix 자동 추가:

`CRAWLER_ENV=production` → `skku_notices` (suffix 없음), `development` → `skku_notices_dev`, `test` → `skku_notices_test`.

`CRAWLER_ENV` 값은 case-insensitive (`TEST`, `Development` 등 허용).

## Environment

`env.py`에서 중앙 관리. `.env` 파일 (`py/.env`) 또는 시스템 환경변수로 설정. `load_dotenv(override=False)` 사용하므로 시스템 ENV가 `.env`보다 우선 (Docker 배포 시 안전).

- `MONGO_URL` — MongoDB 연결 문자열. PR 8부터 설정 로딩은 이걸 강제하지 않는다(저장소 없는 실행이 정당한 상태). 대신 `shared.db.get_client()`가 `MongoUrlMissing`을 던지고, production 프로파일은 기동을 거부한다
- `MONGO_DB_NAME` — 기본: `skku_notices`
- `CRAWLER_ENV` — `production` / `development` / `test` (case-insensitive)
- `LOG_FORMAT` — `json` (기본) / `dev` (컬러 콘솔)
- `AI_SERVICE_URL` — AI 요약 서비스 URL. 환경별 자동 결정: `production` → `http://ai:4000`, `development`/`test` → `http://127.0.0.1:4000`. 직접 지정 시 우선
- `DISCORD_WEBHOOK_URL` — 크롤 헬스 알림용 Discord webhook (선택). 미설정 시 알림만 조용히 스킵 (부팅 로그로 상태 1회 고지). 소스가 연속 3틱 page-0 실패하면 1회 알림 + 회복 알림, 매일 09:00 KST 일일 요약. URL은 시크릿 — 레포 커밋 금지
- `CRAWL_SOURCE_FILTER` — 콤마 구분 학과 ID 필터 (e.g. `skku-main,law`). **dev 오버라이드 전용** ⚠️ 프로덕션 미설정 원칙. 미설정 시 `sources.json`의 `crawlEnabled: true` 항목만 크롤링

**bus 가족** (전부 시크릿. 미설정 시 production은 기동 거부, 그 외는 가족 스킵 — 단 선택된 가족이 전부 스킵되면 어디서든 거부):

- `MONGO_DB_NAME_BUS_CAMPUS` — bus 전용 DB. **기본값 없음** — skkuverse-server가 같은 변수를 기본값 없이 요구하고, 크롤러가 이름을 지어내면 서버가 읽지 않는 곳에 쓰게 된다(에러 없음, 앱만 빈 화면). `db_name_for()`가 환경 suffix를 붙이며 서버의 `devDbName()`과 규칙이 같다
- `API_HSSC_NEW_PROD` / `API_HSSC_NEW_DEV` — HSSC 셔틀 엔드포인트. **URL 전체가 자격증명**이라 로그에 절대 남기지 않는다. production은 `_DEV`로 폴백하지 않는다
- `SEOUL_BUS_SERVICE_KEY` — 서울 TOPIS 키. **URL-encoded여야 한다**(`A-Za-z0-9_%-`). 인코딩 안 된 키는 에러가 아니라 "인증만 안 되는 정상 요청"을 만든다 — 그래서 모듈 생성 시점에 검증하고 거부한다
- `NAVER_API_KEY_ID` / `NAVER_API_KEY` — 네이버 Directions (campus ETA). `bus-eta` 가족만 필요하다 — 이게 만료돼도 셔틀 전광판은 계속 돈다(가족을 둘로 나눈 이유)


## Testing

Python 테스트는 `py/tests/`에 위치. `respx`로 httpx 요청 목킹, `conftest.py`에서 MongoDB를 autouse fixture로 전역 목킹. `asyncio_mode = "auto"` 설정으로 async 테스트 자동 처리.

`conftest.py`의 `_test_env_and_config` autouse fixture가 매 테스트마다 `reset_config()` + `CRAWLER_ENV=test` 설정. `_mock_db`는 이 fixture에 명시적으로 의존하여 실행 순서 보장.

## Adding New Modules

전체 절차와 함정은 `docs/adding-a-module.md`. 요약:

1. **아키타입을 고른다** — 항목 스트림(notices처럼 페이지네이션+dedup) vs 스냅샷(키당 문서 하나 통째 교체). 애매하면 스냅샷.
2. `py/src/skkuverse_crawler/modules/<module>/` 생성 + `CrawlModule` Protocol 구현 (run, shutdown, config)
3. `wiring.py`의 `_FAMILIES`에 `ModuleFamily` 항목 추가 (모듈 이름·필요 `Config` 속성·빌더). 선언한 이름과 실제 빌드 결과가 어긋나면 `WiringError`
4. 저장은 **주입받는다** — `modules/`는 `plugins/`도 `shared.db`도 import할 수 없다 (AST 테스트가 강제)
5. `ModuleConfig.misfire_grace_time`을 주기에 맞게 — misfire는 coalesce보다 먼저 판정되고 기본 10초는 빠른 폴러의 틱을 삼킨다
6. `record_and_alert`의 `threshold`를 주기에 맞게 — `THRESHOLD=3`은 30분 크롤엔 90분, 10초 폴러엔 30초
