# 코어/플러그인 분리 — 단계별 작업 계획

크롤러를 인프라 없이 도는 코어 + 플러그인으로 가르는 작업의 **전체 로드맵**. 설계는 [core-plugin-architecture.md](core-plugin-architecture.md), 결정 근거는 [decisions/adr-006](decisions/adr-006-core-plugin-split.md).

**진행 원칙**: PR 순서대로, `dev`에서 딴 feature 브랜치 → 검증 게이트 통과 → dev PR. main은 merge-only. 매 PR은 **테스트 green + 프로덕션 동작 바이트 동일**을 유지한다. 싼 순수 이동으로 import 그래프를 먼저 무해화하고, 가장 위험한 orchestrator 해체를 맨 뒤로 민다.

**베이스라인**: `python -m pytest --collect-only -q` → **432 tests** (2026-07-30 실측).

**설계 버전**: v2 (2026-07-30 설계 리뷰 라운드 개정 — `CrawlMode` 합 타입·이벤트 2계층 등, [adr-006 근거 ⑦~⑬](decisions/adr-006-core-plugin-split.md)). **구현 착수는 설계 동결 후.**

**선행 조건**: 작업 트리가 깨끗해야 한다. 현재 미커밋분(`skku_standard.py`, `sources.json`, `docs/`)을 먼저 정리할 것 — PR 0의 골든은 커밋된 상태를 기준으로 떠야 한다.

## 상태 보드

| PR | 내용 | 성격 | 위험 | 브랜치 |
|----|------|------|------|--------|
| 0 | 검증 하네스 — FakeCollection + **적합성 테스트** + 골든. `src/` 무변경 | test | – | `test/crawl-golden` |
| 1 | `SystemExit` 지뢰 제거 — 지연 `get_config()` 폐지 | semantic | MED | `refactor/config-explicit` |
| 2 | `DeptResult`→`core/results`, `STRATEGY_MAP`→`strategies/__init__` | 순수 이동 | LOW | `refactor/break-cycles` |
| 3 | **`sources.py` 경로 경화 — 파일 이동보다 먼저** | semantic | MED | `fix/sources-path` |
| 4 | `git mv` 골격: `core/`, `modules/notices/`. `collection_name` 삭제 | 순수 이동 | LOW-MED | `refactor/layout` |
| 5 | `core/ports.py`+`events.py`, `plugins/mongo/{seen,sink,work_seed}`, `dedup.py`→`policy.py` | semantic | MED-HIGH | `refactor/ports` |
| 6 | **orchestrator 해체** — `iter_source`+`run_source` | semantic | **HIGH** | `refactor/crawl-loop` |
| 7 | `Stage`/`Pipeline`, 나머지 플러그인 이관, health 훅화 | 이동+semantic | MED | `refactor/plugins` |
| 8 | pyproject extras + 지연 click + Dockerfile **동일 커밋** | packaging | MED | `feat/extras` |
| 9 | 공개 API re-export, README, 무env 예제 | docs | LOW | `docs/oss-readme` |

의존 순서: 0 → 1 → 2 → **3 → 4** → 5 → 6 → 7 → 8 → 9. **3이 4보다 먼저인 것은 양식이 아니라 필수** (위험 ①).

---

## PR 0 — 검증 하네스 [오라클 확립]

이 PR이 나머지 전부의 안전망이다. `src/`는 한 줄도 건드리지 않는다.

### ① conftest 교체 — 조용한 실패를 시끄러운 실패로

현행 `_mock_db`는 **구조적으로 고장나 있다**. `skkuverse_crawler.shared.db.get_db`를 패치하지만 모든 소비자가 import 시점에 `from ..shared.db import get_db`로 원본을 바인딩한다. 그래서 `run_crawl` 종단 테스트가 아예 없다. 바인딩 지점을 전부 패치하는 건 갱신을 잊게 되는 목록이므로, **진짜 연결을 불가능하고 시끄럽게** 만든다.

- [ ] `_no_real_mongo` autouse fixture — `AsyncIOMotorClient.__init__`이 `AssertionError`를 던지게. 누수가 30초 타임아웃이 아니라 빨간 테스트가 된다
- [ ] DB가 필요한 테스트는 `fake_db` fixture로 명시 opt-in

### ② FakeCollection (~150줄)

필요한 연산자만, 그 이상은 없다.

- [ ] `find(filter, projection)` → **async 이터러블 커서** (이것만으로 `find_existing_meta`·`find_null_content`가 테스트 가능해진다 — 현재 `AsyncMock`이 `async for`를 못 해서 커버리지 0)
- [ ] `update_one(upsert=True)` + 정직한 `upserted_id`, `$set`/`$setOnInsert`/`$inc`/`$push`(`$each`+`$slice: -20`)
- [ ] `bulk_write([UpdateOne], ordered=False)`, `create_index`, `count_documents`, `find_one_and_update`+`ReturnDocument` — 구현 시 발견: `update_checker.py:250`의 실사용은 **aggregation-pipeline update**(`$add/$ifNull/$cond`) 형태. FakeCollection은 문서형만 구현하고 pipeline형은 정직하게 `NotImplementedError` (골든 경로 미사용 — PR 5/6에서 update_checker 이관 시 재검토)
- [ ] **`.ops`** — 인자까지 담은 순서 있는 연산 목록. 골든의 핵심 산출물이며, `mongomock-motor` 대신 손으로 만드는 유일한 이유(최종 상태가 아니라 **왕복 횟수와 순서**가 필요)
- [ ] **미지원 연산자는 `NotImplementedError`** — 조용히 무시 금지. 가짜가 거짓말하는 실패 유형이 통째로 이거다: 나중에 누가 `$unset`을 추가하면 가짜는 무시하고 골든은 통과하는데 프로덕션만 다르게 동작한다. 5줄로 이 부류 전체를 막는다
- [ ] **datetime을 ms로 절삭** — BSON은 밀리초, `datetime.now(timezone.utc)`는 마이크로초. 안 맞추면 실제 Mongo와 상태 비교가 깨진다 (그리고 이게 적합성 테스트가 잡아야 할 바로 그 종류의 버그다)

### ③ 적합성 테스트 — 가짜를 검증하는 테스트 ⭐

> 계획 전체가 골든에 의존하고 골든은 손으로 만든 가짜에 의존한다. **여기 버그가 있으면 골든이 거짓말을 한다.** 특히 `$push`+`$each`+`$slice: -20`, `bulk_write(ordered=False)`, `find_one_and_update`+`ReturnDocument`처럼 흉내 내기 쉬운 만큼 틀리기도 쉬운 연산자가 그렇다.

`tests/conformance/test_fake_collection_conformance.py`, `@pytest.mark.mongo`.

- [ ] 실제 Mongo 확보: **`testcontainers[mongo]` 우선** (컨테이너라 프로덕션 오기입이 구조적으로 불가능), Docker 없는 환경은 `MONGO_TEST_URL` 폴백. 어느 쪽이든 일회용 DB명 + teardown drop
- [ ] `pyproject.toml`: dev extras에 `testcontainers[mongo]`, `[tool.pytest.ini_options]`에 `markers = ["mongo: 실제 MongoDB 필요"]` + `addopts = "-m 'not mongo'"` (기본 제외, `-m mongo`로 명시 실행)
- [ ] **레벨 1 — 연산자 단위 (table-driven)**: 동일 연산 시퀀스를 두 백엔드에 흘리고 최종 상태 대조 (`_id` 제외)
  - `$push`+`$each`+`$slice: -20` — 기존 배열 길이 **0 / 19 / 20 / 21** 경계 + `$each` 다건
  - `bulk_write(ordered=False)` — 중간 op가 duplicate key로 실패해도 나머지가 계속되는 케이스 포함
  - `find_one_and_update` + `ReturnDocument.AFTER` / `.BEFORE`
  - `update_one(upsert=True)` — insert 시 `upserted_id` 존재 / update 시 `None`, **update에는 `$setOnInsert` 미적용**
  - `find` 필터: `$in`, `$or`, `$ne`, `$exists`, `$gte`, `$not: {$gte: 3}` (요약 모듈 질의)
  - `(articleNo, sourceId)` unique 인덱스 위반
- [ ] **레벨 2 — 시나리오 대조**: 골든 시나리오 중 최소 1개(`skku-standard`, 3회전 전체)를 실제 Mongo에 돌려 **최종 컬렉션 상태**가 FakeCollection 결과와 일치하는지 대조
- [ ] 한계를 문서에 명시: `.ops`는 실제 Mongo가 노출하지 않으므로 대조 불가. **레벨 2는 상태를 검증하고, `.ops`는 가짜 전용 왕복 계수 수단으로 남는다.** 이 비대칭을 알고 쓸 것

**탈출구**: 적합성 테스트가 가짜에서 충실도 버그를 **3개 이상** 잡아내면 손으로 만드는 걸 포기하고 뒤집는다 — 골든을 컨테이너의 실제 Mongo에 돌리고 `.ops`는 기록 프록시 래퍼로 딴다. 가짜 유지비가 얻는 것보다 커지는 지점이다.

### ④ 골든 테스트

`tests/characterization/test_crawl_golden.py`. 소스 3종(`skku-standard`, `wordpress-api`, `gnuboard`) × 목록 2페이지 + 상세 ~6건, HTML은 `tests/fixtures/html/`에 동결하고 `respx`로 서빙 (이미 dev 의존).

케이스당 스냅샷 4종: `FakeCollection.ops`(타임스탬프 정규화) · 최종 컬렉션 내용 · `SourceResult` · 로그 이벤트명 순서(`stopped_by`를 노출하지 않고 제어 흐름 경로를 고정).

**같은 FakeCollection에 3회전**:

1. **cold** — 빈 저장소, 전량 조회. 신규 항목 경로
2. **warm, 무변경** — `all_known` early-stop + `has_changed`→False + `bulk_touch_notices`. **이 계획에서 가치가 가장 높은 테스트** (PR 5·6이 깨뜨릴 확률이 가장 높은데 오늘 커버리지 0)
3. **warm, 제목 1건 변조** — `change_detected` → `update_with_history`, `editHistory` 항목 dict를 고정

- [ ] 추가 케이스: 페이지 0 vs 페이지 ≥1의 floor break, 상단고정만 있는 페이지, 페이지 0에서 `crawl_list` 예외(`source_down=True`)
- [ ] 동일 fixture를 무플러그인 구성으로 — 전량 스윕 + `stopped_by == "empty_page"`. **"코어는 아무것도 요구하지 않는다"의 인수 테스트.** PR 0 시점엔 현행 API(`CrawlOptions(incremental=False)` + fake collection)로 특성화하고, PR 6에서 `FullSweep()`+`NullSink`로 갈아끼워 같은 골든이 통과해야 한다 (v2: 전량 스윕은 `NullSeenIndex` 창발이 아니라 `FullSweep` 명명 모드 — adr-006 §⑦)

### ⑤ 구조 테스트 (싸고 영구적)

- [ ] `core` import 후 `sys.modules`에 `motor` 없음 (subprocess)
- [ ] `--help`가 `motor`를 import하지 않음 — `cli.py:104-112` 회귀를 영구 차단
- [ ] `env={}`로 패키지 import 가능
- [ ] AST 스캔: `modules/**`가 `plugins/`를 import하지 않음

**검증 게이트**: 432 tests green. 골든 4종 스냅샷을 **사람이 1회 육안 검수** (자동 생성물을 그대로 신뢰하지 않는다). `-m mongo` 적합성 green.

---

## PR 1 — `SystemExit` 지뢰 제거

- [ ] `configure_logging()`이 `get_config()`를 부르지 않게
- [ ] `get_config()`가 지연 `init_config()` 대신 `ConfigNotInitialized`를 raise
- [ ] 비-CLI 호출 지점 6곳만 손대면 된다: `db.py:14,21`, `discord.py:48`, `logger.py:12`, `notices/module.py:26,55`, `dispatch_client.py:95`, `processor.py:43`

**검증 게이트**: subprocess로 `env={}` 전체 패키지 import → 예외·종료 없음. `conftest`의 `CRAWLER_ENV=test` 강제 fixture가 **존재 이유를 잃는다** (seam 작업이 실재한다는 조기 증거).

## PR 2 — 순환 끊기 [순수 이동]

- [ ] `DeptResult` → `core/results.SourceResult` (`DeptResult = SourceResult` 별칭은 이 PR 한정, 다음 PR에서 삭제)
- [ ] `STRATEGY_MAP` → `modules/notices/strategies/__init__.py`

**검증 게이트**: health logic import 후 `sys.modules`에 `motor`/`pymongo` 없음. **`git diff -M`에 import 문이 아닌 변경 줄이 0** — 하나라도 있으면 순수 이동이 아니므로 다른 PR로 뺀다.

## PR 3 — `sources.py` 경로 경화 [이동보다 먼저]

- [x] `parents[5]` 제거 → `SOURCES_JSON_PATH` → 상향 탐색(`__init__.py` 디렉토리 스킵) → `importlib.resources` 패키지 데이터 (PR #39)
- [x] `sys.exit(1)` → `SourceConfigError` (라이브러리 코드에서 프로세스 종료 금지)
- [x] **`sources.json`만** wheel에 포함 — 구현 시 확인: 런타임이 읽는 파일은 sources.json뿐, categories/exclude-reasons는 codegen 전용이라 패키징 불필요. 방식은 force-include가 아니라 **codegen 유지 사본**(Docker 이미지가 editable 설치라 force-include가 컨테이너에 도달 불가; `generate_artifacts.py` step [9] + 바이트 동일성 테스트)
- [x] 기동 시 `sources_loaded count=N path=…` 로그

**검증 게이트**: `pip wheel . && unzip -l`에 sources.json 존재 ✓. `docker compose build`(bare `docker build`는 additional_contexts 때문에 불성립) + 컨테이너에서 3개 해석 경로 검증 ✓ (실크롤은 컨테이너에 Mongo 부재로 loader 검증 대체 — 크롤 동등성은 골든이 담보).

## PR 4 — 레이아웃 골격 [순수 이동]

- [x] `git mv`로 `core/`, `modules/notices/` 생성 — 구현 시 확정: `notices/` → `modules/notices/` 통째 이동(`config/` 내부 구조 유지 — `data/` 개명은 loader가 `core/sources.py`로 해체되는 PR과 동행), `modules/base.py` → `core/module.py` + `modules/registry.py` → `core/registry.py` (adr-006 근거 ⑥의 side effect — modules/ 네임스페이스 비우기)
- [x] `ModuleConfig.collection_name` 삭제 (4곳 write, 0곳 read) — **이동 전 별도 커밋**으로, `base.py → core/module.py`가 100% similarity rename이 되도록

**검증 게이트**: PR 2와 동일한 `git diff -M` 기계 검사. `docker compose build`(bare `docker build`는 additional_contexts 때문에 불성립) + `docker compose run --rm --no-deps crawler python -m skkuverse_crawler --help`.

구현 시 확인된 diff 게이트 **carve-out** (non-import 변경 줄의 전수 — 이 밖은 게이트 위반):

1. `modules/notices/config/loader.py`의 `resources.files()` 앵커 문자열 (src 유일)
2. `collection_name` 삭제 5줄 (선행 커밋)
3. 테스트의 `mock.patch(...)` 대상 문자열 — `characterization/harness.py`, `test_attachment_validator.py`, `test_orchestrator.py`, `test_update_checker.py`
4. `scripts/generate_artifacts.py`의 `SOURCE_IDS_PY`·`PACKAGE_SOURCES_JSON` 경로 상수 + `tests/scripts/test_generate_artifacts.py`의 Path 표현식

참고 문서 내 구경로(`docs/api-design-reference.md`, `docs/strategies/*.md`, `docs/known-issues.md`의 `py/src/skkuverse_crawler/notices/...` ~20줄)는 PR 9 공개 문서 정비로 연기.

## PR 5 — 포트 도입

- [ ] `core/ports.py`(`Sink`에 `@runtime_checkable`) + `core/events.py` — 베이스 `CrawlEvent(source_id)` + **결과/진행 2계층** (설계 §이벤트, adr-006 §⑧)
- [ ] sink **contract test** — 미지의 이벤트를 `accept`에 넣어 `None` 반환(무시 계약) 확인. 서드파티 sink 작성자에게 제공할 스위트의 원형
- [ ] `plugins/mongo/{seen,sink,work_seed}.py`를 `dedup.py`의 **본문 그대로** 옮겨 구성
- [ ] `dedup.py` → `modules/notices/policy.py` — 순수 술어만 남긴다
- [ ] **기존 루프는 건드리지 않는다.** 포트를 경유하게만 바꾼다
- [ ] `SeenRecord.content_hash: str | None = None` — 기본값 필수 (위험 목록 참조)

**검증 게이트**: PR 0 골든 바이트 동일 + 플러그인 없는 스윕 테스트. **`-m mongo` 적합성 재실행** (store 의미를 건드리는 PR이므로).

## PR 6 — orchestrator 해체 ⚠️ 최고 위험

**2개 커밋으로 나눠 올린다**: (A) sink 호출은 러너에 인라인으로 둔 채 `iter_source`만 제너레이터로 추출 → **이벤트 순서**가 맞는지 증명. (B) 뒤집기. 리뷰어가 A를 "이벤트가 옳은 순서로 나왔나", B를 "sink가 그걸로 옳은 일을 했나"로 따로 읽을 수 있다.

- [ ] `iter_source` + `run_source`
- [ ] `CrawlOptions.incremental` 삭제 → `CrawlMode = Incremental(seen) | FullSweep` (설계 §CrawlMode). `case FullSweep(): meta, all_known = {}, False` **명시 대입** — v1 골격의 잠복 UnboundLocalError를 구조 해소
- [ ] `max_pages` 유도 보존: 미지정 시 Incremental→100 / FullSweep→2500. `WorkSeed`는 mode와 직교 파라미터 (adr-006 §⑫ — 전량 재크롤도 백필 수행)
- [ ] `_process_page_smart`/`_process_page_full` 병합
- [ ] `SERVICE_START_DATE` → `options.since_date` (notices 모듈이 현행 값을 기본 공급)

**검증 게이트**: 골든 바이트 동일. **`-m mongo` 적합성 재실행.** scratch DB 대상 shadow run 후 문서 대조.

## PR 7 — 나머지 플러그인 이관

- [ ] `Stage`/`Pipeline` + `ContentDoc` (설계 §Stage — **팬아웃**이지 체인이 아님)
- [ ] `notices_summary` → `plugins/{ai_summary,dispatch}`
- [ ] `crawl_health` → `plugins/health` + `core.ports.Notifier`
- [ ] `scheduler` 플러그인화, validators 3분할
- [ ] `notices/module.py:29`의 `record_and_alert`를 wiring이 설치하는 훅으로
- [ ] wiring 조립 시점 `isinstance` 검증 — `@runtime_checkable` 기반, `flush` 누락 등이 부팅 시 명확한 에러 (설계 §런타임 검증)

**검증 게이트**: 골든. health logic 테스트 무수정 통과.

## PR 8 — extras + 패키징

- [ ] `[project.optional-dependencies]`: `mongo`(motor) / `discord`(tenacity) / `ai` / `sched`(apscheduler) / `all`
- [ ] click 서브커맨드 지연 로딩, `py.typed`
- [ ] ⚠️ **Dockerfile `uv sync --extra mongo --extra sched --extra discord --extra ai`를 같은 커밋에** — 현재 `uv sync --frozen --no-dev`는 motor가 extras로 빠지는 순간 **mongo 없이 설치**되어 이 PR이 위험 ⑤를 스스로 만든다

**검증 게이트**: 클린 venv에 코어만 설치 → 1페이지 stdout 크롤. `docker build`가 머지 게이트.

## PR 9 — 공개 문서

- [ ] `core/__init__.py` 공개 API re-export, README, env 없는 예제
- [ ] `core/simple.py` — `iter_notices()` facade가 README 첫 예제 (기본 `max_pages` 작게 — FullSweep 2500페이지로부터 캐주얼 사용자 보호)
- [ ] 버전 **0.x** + README에 "1.0 전 이벤트 스키마는 minor에서 변경 가능" 명시. **1.0은 schedule 모듈 탑재 후** (adr-006 §⑬ 게이트)
- [ ] sink 작성자 가이드 — contract test 사용법 + "이벤트 자체를 버퍼링하지 말 것"(5MB `cleanHtml` GC 경고, 설계 §알려진 한계)
- [ ] **검증 게이트**: README 예제가 CI에서 실제로 실행된다

---

## 위험

| # | 위험 | 완화 |
|---|------|------|
| ① | **`parents[5]`가 파일 이동 시 재조준된다.** `notices/config/loader.py:14-17`이 import 시점에 경로를 계산한다. 실측: `py/Dockerfile:26`이 `sources.json`을 `/sources.json`에 복사하고 `SOURCES_JSON_PATH`를 **설정하지 않는다** → 컨테이너에서 `parents[5] == /`가 곧 프로덕션 경로. 한 단계만 깊어져도 `/app/sources.json`을 가리키고 없는 파일이라 기동 실패 | 경로 해결을 **별도 PR(3)에서, 이동 전에** 고친다. `sources_loaded` 로그. PR 3·4를 `docker build` + 실크롤로 게이트 |
| ② | **`bulk_touch_notices`가 조용히 증발한다** — seam이 맨 `Notice`를 흘리면. 아무것도 raise 안 하고 카운터는 정상, `crawledAt`만 136개 소스에서 멈춰 한 달 뒤 발견 | `NoticeUnchanged`를 1급 이벤트로, `Sink.flush()`를 프로토콜에 처음부터. 골든 op 순서가 페이지당 `bulk_write` 정확히 1회 + 문서 수를 단언 |
| ③ | **early-stop 술어의 의미가 이동 중 바뀐다.** `should_continue`·`page_below_floor`는 인시던트 수정 2건(상단고정 제외, U+FFFD 절단)을 품고 있다. 상단고정을 다시 포함하면 소스당 틱당 100회 목록 조회를 조용히 낭비하고, floor break를 페이지 0 처리 앞으로 옮기면 신규 상단고정 공지를 영구 유실한다 | 세 함수를 **바이트 동일 복사**로, 기존 테스트를 붙인 채, 다른 걸 아무것도 안 고치는 PR에서 옮긴다. **이동과 수정을 같은 커밋에 두지 않는다.** 시나리오별 `stopped_by` 골든 단언 |
| ④ | **null-content 백필 경로를 "통합"하려는 유혹.** `orchestrator.py:180-210`은 의도적으로 다른 산출을 낸다 — `build_notice` 우회, dimension 미주입, 특정 필드만 `$set`. 중복처럼 보여 정리하고 싶어지는데, `Pipeline`을 태우면 백필된 모든 문서의 `cleanHtml`이 에러 없이 재작성된다 | 별도 `ContentRefreshed` 이벤트 + 필드 목록 명시적 열거 + 골든 고정 + "이 분기는 의도적"이라는 주석 |
| ⑤ | **선택적 설정이 누락을 침묵 no-op으로 바꾼다 — §7의 상위 호환.** 지금은 `MONGO_URL` 누락 = 종료. 이후엔 "mongo 플러그인 없음"이 정당한 상태라, `MONGO_URL`을 잃은 배포가 136개 소스를 전량 크롤·전량 상세 조회하고 아무것도 안 쓴 뒤 깨끗한 성공을 로그한다 | `build_runtime(settings, profile="production")`이 필수 플러그인 부재 시 기동 거부. 부팅 `active_plugins=[...]` 로그 + 09:00 Discord 요약 포함. 테스트: production 프로파일 + 빈 environ → raise |
| ⑥ | **`dict` → `SeenRecord` 변환 (PR 5).** 현행 `existing.get("contentHash")`는 키 부재를 견딘다. 필수 필드 dataclass면 크롤 도중 `TypeError` → 항목별 `except Exception`에 잡혀 **에러로 조용히 계수** | `content_hash: str | None = None` 선언 |
| ⑦ | **적합성 테스트 부재 시 골든이 거짓말한다** (PR 0 §③) | 적합성 테스트를 후속이 아니라 **PR 0의 일부**로. 나중에 붙이면 PR 1~4가 검증되지 않은 가짜로 "검증"된 상태가 된다 |
| ⑧ | **콜드스타트 최적화 유혹.** `Incremental` + 빈 DB에서 `meta={}`는 정상인데, 누군가 `should_continue`에 `if not meta: return False`를 넣으면(함수명만 보면 합리적) 첫 크롤이 첫 페이지에서 멈춘다. v1의 창발 위험은 `CrawlMode`로 구조 해소됐지만 이 잔여분은 남는다 | `should_continue` docstring ↔ 골든 cold run이 서로를 명시적으로 가리키는 양방향 상호 참조. 골든 run 1(cold)이 전량 조회를 고정 |
| ⑨ | **이벤트 스키마 = 공개 API (Hyrum's Law).** 공개 순간 이벤트 이름·필드·순서에 누군가 의존한다. 뒷면도 있다: 결과 이벤트를 진행 계층으로 오분류하면 tolerant reader 계약 때문에 서드파티 sink가 **조용히 데이터를 유실**한다 | 결과 계층은 1.0 전 동결(추가=major), 진행 계층만 minor 추가. 계층 분류를 adr-006 §⑧ 표로 고정하고 리뷰에서 오분류 검사. contract test를 서드파티에 제공. 0.x 기간이 수정의 마지막 창문 |

**추가 (~5줄)**: 실행당 `crawl_coverage attempted=N enabled=M` 로그 + 골든 고정. §7 인시던트가 며칠간 안 보였던 이유가 attempted와 enabled를 아무도 대조하지 않아서였다.

---

## 검증 명령

```bash
cd py
.venv/bin/python -m pytest tests/ -q                     # 432 베이스라인, 줄면 안 됨
.venv/bin/ruff check src/ && .venv/bin/mypy src/
.venv/bin/python -m pytest tests/characterization -q     # 골든 바이트 동일
.venv/bin/python -m pytest -m mongo -q                   # 적합성 (PR 0·5·6 게이트)
```

코어 무설정 인수 (PR 8 이후), **extras 없는 클린 venv + `.env` 없음**:

```bash
pip install ./py
python -c "import skkuverse_crawler.core, sys; assert 'motor' not in sys.modules"
env -i PATH=$PATH skku-crawl notices --source skku-main --pages 1 --json
```

프로덕션 동등성 (PR 3·4·6·8 머지 게이트):

```bash
docker build -f py/Dockerfile .
docker run --rm <img> python -m skkuverse_crawler --help   # motor를 import하면 안 됨
.venv/bin/python -m skkuverse_crawler notices --once --source skku-main --pages 2
```

shadow run 후 MongoDB MCP(읽기 전용)로 필드 형태 드리프트 확인 — 표본 `sourceId`의 `cleanHtml`·`cleanMarkdown`·`contentHash`·`editHistory`·`crawledAt`를 리팩터 전 문서와 대조. **무변경 공지의 `crawledAt`이 갱신되는지**가 위험 ②의 전용 검사다.

---

## 이번 작업 범위 밖 (의도적)

- **SKKU 비종속 범용 프레임워크** — strategy는 번들 유지, `sources.json`은 패키지 데이터로 동봉. 서드파티 strategy의 entry point 발견은 이후 추가(파괴적이지 않음)
- **다중 PyPI 배포물 분리** (`skkucrawl-core`/`-mongo`) — 단일 배포물 + extras. 경계는 AST 레이어링 테스트가 지킨다
- **퍼블릭 코어 레포 분리** — 단일 레포 유지
- **`schedule` 모듈 부활** — 이 리팩터가 싸게 만들어주지만 `feat/schedule-crawler` 포팅은 별건
- **MongoDB 교체나 스키마·인덱스 변경** — 문서 형태 그대로
- **`pluggy`** — 확장점 4개에 정당화 안 됨. Protocol + 레지스트리가 더 읽힌다
- **Pydantic** — 현행대로 dataclass
- **`update_checker`의 stale `cleanMarkdown`** — Tier-2 변경 시 `cleanHtml`·`contentHash`는 재작성하면서 `cleanMarkdown`은 재계산하지 않는 실제 버그. 분리와 무관하므로 **별건으로 등록** (바이트 동일 골든을 오염시키지 않기 위해)
