# Core / Plugin Architecture — 오픈소스 코어 설계

크롤러를 **인프라 없이 도는 코어**와 **인프라를 붙이는 플러그인**으로 가르는 설계. 결정 배경은 [decisions/adr-006](decisions/adr-006-core-plugin-split.md), 작업 순서는 [core-plugin-plan.md](core-plugin-plan.md) 참조.

> **상태**: 설계 v2. **PR 0~9 구현 완료 (2026-08-02) — 로드맵 종료.** Stage/Pipeline은 `core/pipeline.py`(모양) + `modules/notices/stages.py`(구체 스테이지, 설계 스케치의 `core/content/`와 다름: 사유는 plan.md PR 7 확정 사항), 조립 시점 검증은 `wiring.py`의 `_require`, flush 계약은 `core/runner.py`. PR 8(extras) — optional-dependencies + 지연 click group + `env.py`/`core/settings.py` 분리 + production 부팅 거부(`wiring.ProfileError`) + `core/sinks.JsonLinesSink`. PR 9(공개 문서) — `core/__init__` 재수출 + `core/testing.assert_sink_contract` 출하 + 버전 0.1.0 + 레포 루트 README(CI가 실행하는 예제) + [sink 작성자 가이드](sink-authors-guide.md).
>
> **⚠️ 이 문서는 설계안이다. 현재 코드 배치는 [architecture.md](architecture.md) §Directory Layout이 정답이다.**
>
> 아래 §레이아웃은 **구현 전 스케치**이며 실제와 9곳 다르다. 지우지 않고 남기는 이유는 무엇을 설계했고 무엇이 살아남았는지가 그 자체로 기록이기 때문이다 — 어긋난 지점은 전부 여기 적는다.
>
> | 설계 스케치 | 실제 구현 | 사유 |
> |------------|----------|------|
> | `core/simple.py`의 `iter_notices()` | `modules/notices/simple.py` + 최상위 PEP 562 지연 재수출 | PR 6이 `iter_source`를 modules 소유로 확정 → core의 facade가 자기가 감쌀 대상을 부를 수 없다 (adr-006 근거 ⑦~⑬, plan.md PR 9) |
> | **`shared/` 해체** | **`shared/`는 그대로 남아 있다** — `db.py`·`logger.py`·`fetcher.py`·`html_cleaner.py`·`html_to_markdown.py` | 이 리팩터의 범위 밖. 층 경계(core/modules/plugins)를 세우는 것이 목표였고 `shared/`는 미배정 상태로 유예됐다 |
> | `core/net/fetcher.py` | `shared/fetcher.py` | 위와 같음 |
> | `core/logging.py` | `shared/logger.py` | 위와 같음 |
> | `core/content/{html_cleaner,html_to_markdown}.py` | `shared/`에 잔류 | 위와 같음 |
> | `core/content/stages.py` | `modules/notices/stages.py` | 코어는 **모양만**(`core/pipeline.py`), 구체 스테이지는 콘텐츠 의미를 소유한 모듈에 (plan.md PR 7) |
> | `core/content/hashing.py` | `modules/notices/hashing.py` | 위와 같음 |
> | `core/models.py` | `modules/notices/models.py` | Notice는 공지 도메인 모델. 코어에 남은 결과 타입은 `core/results.py`의 `SourceResult` |
> | `modules/notices/{crawler.py, data/}` | `{orchestrator.py, config/}` | `data/` 개명은 loader가 `core/sources.py`로 해체될 때로 유예 |
> | `plugins/health/{logic,state}.py` | `plugins/health/{logic,store,module,cli}.py` | 일일 요약 모듈과 CLI 리프가 추가됨 |
>
> **불변식**: `core/`는 `modules/`·`plugins/`를 import하지 않는다. `modules/`는 `plugins/`를 import하지 않는다. `plugins/`를 import하는 파일은 **조립 리프뿐** — `wiring.py`, 루트 `cli.py`, 각 플러그인의 `cli.py` *(PR 7 개정, adr-006 §발동 기록)*. `os.environ`을 읽는 파일은 `env.py` 하나 — *(PR 8 정정)* 실제로는 **둘**: `env.py`와 `modules/notices/config/loader.py`(SOURCES_JSON_PATH). 경로 해석이 Config 생성보다 먼저라 구조적으로 불가피하며, `test_env_is_the_only_environment_reader`의 허용목록이 두 항목을 명시한다. — AST 테스트로 강제. *(v2)* 증분/전량 같은 실행 모드는 bool 플래그가 아니라 **합 타입**으로 — 불법 조합은 런타임 검증이 아니라 타입 구조로 차단한다.

## 목표 상태

```bash
pip install skkuverse-crawler                      # 코어만
env -i skkuverse-crawler notices --source skku-main --pages 1 --json   # DB·env·웹훅 없이 동작

pip install skkuverse-crawler[mongo,discord,ai,sched]           # 프로덕션
```

```python
# 캐주얼 사용자 (README 첫 예제) — facade
async for notice in iter_notices(source, strategy):
    print(notice.title, notice.cleanMarkdown)

# 고급 사용자 — 이벤트 스트림
async for ev in iter_source(source, strategy, mode=Incremental(seen=my_index)):
    ...
```

## 레이아웃

> **구현 전 스케치다.** 실제 배치는 [architecture.md](architecture.md) §Directory Layout 참조 — 차이 9곳은 문서 상단 표에 정리돼 있다.

```
skkuverse_crawler/
  core/                      # 인프라 0. env 읽기 없음, 서비스 없음, SystemExit 없음.
    models.py results.py ports.py events.py pipeline.py module.py registry.py
    settings.py              # 명시적 frozen dataclass — 스스로 로드하지 않는다
    logging.py               # get_config() 없는 get_logger
    net/fetcher.py
    content/{html_cleaner,html_to_markdown,hashing,stages}.py
    sources.py               # 로더 + 스키마. SourceConfigError를 raise, sys.exit 금지
    crawl.py                 # iter_source + CrawlMode
    runner.py simple.py      # 이벤트→sink 러너 / iter_notices() facade
  modules/
    notices/{policy.py, validation.py, crawler.py, models.py, strategies/, data/}
    schedule/                # 이후 (feat/schedule-crawler 8ad3e8e 포팅)
  plugins/
    mongo/{seen.py, sink.py, work_seed.py, update_checker.py, audit.py}
    health/{logic.py, state.py}
    discord/ ai_summary/ dispatch/ scheduler/
  env.py                     # settings_from_env(). os.environ/dotenv 유일 접점
  wiring.py                  # build_runtime(settings, profile). plugins import 유일 접점
  cli.py                     # click 루트, 서브커맨드 지연 로딩
  py.typed
```

`shared/`는 해체된다: `config.py` → `env.py` + `core/settings.py` / `db.py` → `plugins/mongo` / `discord.py` → `plugins/discord` / `fetcher.py` → `core/net` / `html_cleaner.py`·`html_to_markdown.py` → `core/content` / `logger.py` → `core/logging.py`.

> *(구현 결과)* **6개 중 2개만 실행됐다.** `config.py` → `env.py` + `core/settings.py` ✅, `discord.py` → `plugins/discord/webhook.py` ✅. 나머지 4개(`db`·`fetcher`·`html_*`·`logger`)는 `shared/`에 그대로 있다. 층 경계를 세우는 것이 이 리팩터의 목표였고, 이미 경계를 넘지 않는 파일을 옮기는 일은 이득 없이 diff만 키운다고 판단해 유예했다. `architecture.md`의 트리가 이 상태를 "아직 층에 배정되지 않은 공통 코드"로 표기한다.

조립부를 `app/` 패키지가 아니라 리프 모듈 3개로 두는 이유: 아무도 import하지 않는 리프라 코어 전용 설치가 이 파일들을 건드리지 않는다.

> *(PR 8 기각)* 같은 논리로 `click`·`python-dotenv`까지 기본 의존성에서 빼자는 결론은 채택하지 않았다. `[project.scripts]`가 콘솔 스크립트를 선언하는 이상, 코어 전용 설치가 동작하는 바이너리를 만들지 못하면 §목표 상태의 `env -i skkuverse-crawler notices …` 인수 조건이 구조적으로 불가능해진다. 레이어링 주장(리프는 아무도 import하지 않는다)은 유효하지만 패키징 결론은 따라오지 않는다.

## 논쟁 지점의 귀속

| 조각 | 목적지 | 이유 |
|------|--------|------|
| `has_changed`, `should_continue`, `page_below_floor` | `modules/notices/policy.py` | 순수 함수지만 **SKKU 목록 페이지 고유**. 코어 아님(`schedule`의 변경 감지는 전혀 다름). 플러그인도 아님 — `has_changed`가 U+FFFD 절단 방어를 품고 있어 저장소에 두면 플러그인 없는 실행에서 사라지고 백엔드마다 재구현해야 함 |
| `DeptResult` → `SourceResult` | `core/results.py` | `notices ↔ crawl_health` 순환을 끊고, **동시에** health가 임의 모듈의 산출을 소비하게 함. `notices/models.py`로 옮겨도 순환은 풀리지만 health가 notices 전용으로 굳음 |
| `SERVICE_START_DATE = "2026-03-09"` | `CrawlOptions.since_date` | 코어 상수가 아니라 배포 정책. notices 모듈이 현행 값을 기본값으로 공급 → 프로덕션 무변화. OSS 기본값은 `None` |
| `STRATEGY_MAP` | `modules/notices/strategies/__init__.py` | 전략 레지스트리인데 DB에 묶인 orchestrator 안에 살아서 `update_checker.py:19`가 Mongo를 끌고 옴 |
| `attachment_validator.py:88-175`, `markdown_validator.py:129-238` 순수 검사 | `modules/notices/validation.py` | 이미 순수 |
| 위 두 파일의 DB 스캔 드라이버 | `plugins/mongo/audit.py` | |
| `update_checker.py` 전체 | `plugins/mongo/` | 전면 DB 주도(14일 창 질의 → 재조회 → 해시 비교 → soft-delete). 유일한 장애물이 `STRATEGY_MAP` import |
| `image_verifier.py` | `modules/notices/stages.py`의 **선택** 스테이지 *(스케치는 `core/content/stages.py`)* | 코어 자격 있음(httpx + imagesize)이나 당시 무조건 실행. 게시판 하나 긁는 OSS 사용자가 공지당 N회 추가 HTTP를 끌 수 있어야 함 → 구현됨: `VerifyImages`를 `DEFAULT_PIPELINE.without("verify-images")`로 끌 수 있다 |
| `Notifier` 프로토콜 | `core/ports.py` | Discord는 구현 하나. `plugins/health` → `plugins/discord` 하드 엣지 회피 |
| `ModuleConfig.collection_name` | **삭제** | 4곳에서 쓰고(`notices/module.py:18,47`, `notices_summary/module.py:14`, `crawl_health/module.py:73`) 읽는 곳 0. 코어 계약에 박힌 DB 개념 |

## seam — 무상태 코어 / 유상태 플러그인

포트는 **3개**다. 2개(읽기/쓰기)로 묶으면 `find_null_content`가 어디에도 안 맞아 코어로 되밀항한다.

```python
# core/ports.py
@dataclass(frozen=True)
class SeenRecord:
    article_no: int
    title: str
    date: str
    content_hash: str | None = None      # 기본값 필수 — 현행이 existing.get("contentHash")

class SeenIndex(Protocol):               # 읽기: 무엇을 이미 봤나
    async def lookup(self, source_id: str,
                     article_nos: Sequence[int]) -> Mapping[int, SeenRecord]: ...

class WorkSeed(Protocol):                # 저장소가 작업을 주입: find_null_content
    async def pending_refs(self, source_id: str) -> Sequence[DetailRef]: ...

@runtime_checkable                       # (v2) 조립 시점 isinstance 검사용 — 아래 §런타임 검증
class Sink(Protocol):                    # 쓰기
    async def prepare(self, source: SourceSpec) -> None: ...   # ensure_indexes
    async def accept(self, event: CrawlEvent) -> Outcome | None: ...
    async def flush(self) -> None: ...                          # 모아둔 touch를 배출

# 코어 기본값: NullWorkSeed(()) / NullSink(None).
# (v2) NullSeenIndex는 기본값이 아니다 — 테스트 스텁으로만 존치. 증분 여부는 CrawlMode가 결정한다(아래).
```

`flush()`는 선택이 아니다 — 현행 `bulk_touch_notices`는 페이지 단위로 모아 `bulk_write(ordered=False)` 한 번을 쏜다. flush 없는 sink는 페이지당 N회 왕복으로 조용히 퇴화한다.

### CrawlMode — 증분/전량을 타입으로 *(v2 개정, adr-006 §⑦)*

```python
# core/crawl.py
@dataclass(frozen=True)
class Incremental:
    """증분 크롤. SeenIndex 없이는 생성 자체가 불가능하다."""
    seen: SeenIndex

@dataclass(frozen=True)
class FullSweep:
    """전량 크롤. 상태를 참조하지 않는다."""

CrawlMode = Incremental | FullSweep
```

- v1의 `CrawlOptions.incremental: bool` + `seen=NullSeenIndex()` 조합을 대체한다. "증분인데 seen 없음"이라는 불법 상태가 **표현 불가능** (make illegal states unrepresentable).
- **기본값이 정직해진다**: `Incremental`은 seen 없이 못 만드므로 기본값은 `FullSweep`일 수밖에 없다. v1 기본값은 "incremental=True인데 몰래 전량 스윕"이라는 거짓말이었다.
- **`WorkSeed`는 mode에 넣지 않는다 (직교 파라미터)** — 리뷰 종합안은 `Incremental` 안으로 넣자고 했으나 기각: `orchestrator.py:180`의 null-content 백필은 incremental 여부와 **무관하게 무조건** 실행된다. "FullSweep + WorkSeed"는 불법 상태가 아니라 현행 프로덕션 동작이다 (adr-006 §⑫).
- `NullSeenIndex`는 테스트 스텁으로 존치 — 더 이상 동작을 만들어내는 장치가 아니다.

### 2계층 API

```python
# core/crawl.py — 고급 사용자·러너가 부르는 것. 저장소도 sink도 없음.
async def iter_source(source, strategy, *,
                      mode: CrawlMode = FullSweep(),
                      work_seed: WorkSeed = NullWorkSeed(),
                      pipeline: Pipeline = DEFAULT_PIPELINE,
                      options: CrawlOptions = CrawlOptions()) -> AsyncIterator[CrawlEvent]

# core/runner.py — 이벤트를 sink에 먹이고 집계.
async def run_source(source, strategy, *, sink: Sink = NullSink(), **kw) -> SourceResult
```

`CrawlOptions`에서 `incremental`은 사라진다(→ `CrawlMode`). 남는 것: `max_pages`·`delay_ms`·`since_date`. `max_pages` 미지정 시 유도는 현행 보존: Incremental→100 / FullSweep→2500.

### 이벤트 — 2계층 + 무시 계약 *(v2 개정, adr-006 §⑧)*

```python
# core/events.py
@dataclass(frozen=True)
class CrawlEvent:
    """모든 이벤트의 베이스. 자기완결적 — sink는 이벤트 하나만 보고 처리할 수
    있어야 한다 (SourceStarted를 기억하는 sink = 상태 보유 = 병렬 크롤에서 위험)."""
    source_id: str
```

| 계층 | 이벤트 | 버전 정책 |
|------|--------|----------|
| **결과** (안정 API) | `NoticeCrawled(notice, previous, change)` · `NoticeUnchanged(article_no, views)` · `ContentRefreshed(ref, fields)` · `ItemFailed(article_no, error)` · `ItemSkipped(article_no, reason)` | 추가·변경 = **major** |
| **진행** | `SourceStarted(source_name)` · `PageCompleted(page)` · `ListFetchFailed(page, error)` · `SourceFinished(stopped_by, source_down, last_error)` | **minor**에서 추가 가능 |

**계약**: sink는 모르는/관심 없는 이벤트를 조용히 무시한다 (`case _: return None`) — tolerant reader. 러너가 진행 이벤트의 의미(`PageCompleted`→`flush()` 호출 등)를 소유하므로, sink는 결과 계층만 알면 충분하다. 내부 sink는 여전히 mypy `assert_never`로 엄격하게 잡는다 — 내부는 릴리스와 함께 갱신되므로 엄격함이 안전망이고, 서드파티는 갱신 시점을 통제 못 하므로 관대함이 안전망이다.

계약은 문서가 아니라 **contract test**로 강제한다 (서드파티 sink 작성자에게 제공):

```python
@dataclass(frozen=True)
class _UnknownFutureEvent(CrawlEvent): ...

async def test_sink_tolerates_unknown_events(sink):
    assert await sink.accept(_UnknownFutureEvent(source_id="test")) is None
```

`ChangeInfo`는 현행 인라인 `edit_entry`가 필요로 하는 것만 담는다 — `detectedAt`·`"source": "tier1"`·`$push`/`$slice: -20`은 플러그인 몫.

### 루프 골격 — early-stop 순서가 하중을 받는다

seen 상담은 **페이지 단위**다. `all_known`이 페이지 루프를 끊기 때문이다. `orchestrator.py:213-268`의 break 지점 4개와 "처리 전 break / 처리 후 break" 순서를 그대로 보존한다.

```python
while page < max_pages:
    list_items = await strategy.crawl_list(...)   # except → ListFetchFailed, source_down=(page==0)
    if not list_items: stopped_by = "empty_page"; break

    is_first    = page == 0
    below_floor = policy.page_below_floor(list_items, since=options.since_date)
    if below_floor and not is_first: stopped_by = "floor_date"; break     # 처리 전 break

    match mode:
        case Incremental(seen=seen):
            meta = await seen.lookup(source.id, [i.articleNo for i in list_items])
            all_known = not policy.should_continue(list_items, meta)
        case FullSweep():
            meta, all_known = {}, False    # 명시 대입 — lookup 호출 없음(현행과 동일),
                                           # 아래 all_known 참조가 무조건 안전해진다

    if not is_first and all_known: stopped_by = "all_known"; break        # 처리 전 break

    async for ev in _emit_page(list_items, meta, ...): yield ev
    yield PageCompleted(source.id, page)

    if is_first and all_known: stopped_by = "all_known_first_page"; break # 처리 후 break
    if below_floor: stopped_by = "floor_date"; break                       # 페이지 0은 처리 후 break
    page += 1
```

- 페이지 0은 floor break **전에 처리**해야 한다 — floor 이후 날짜의 상단고정 행은 거기서만 노출되므로 먼저 끊으면 영구 유실된다 (`orchestrator.py:236-239`).
- v1 골격의 `if options.incremental and is_first and all_known:`은 `else` 분기에서 `all_known`이 미대입이라 `and` 단락 평가로만 보호되는 잠복 `UnboundLocalError`였다. v2는 `FullSweep` arm의 명시 대입으로 구조 해소 — 조건이 `if is_first and all_known:`으로 단순해진다.
- `FullSweep`은 `lookup`을 호출하지 않는다 — 현행 `_process_page_full`이 DB 읽기를 안 하는 것과 동일. "항상 lookup하고 `{}`를 넘기는 통일"은 동작·비용 변경이라 금지.

### FullSweep — 창발이 아니라 명명된 모드 *(v2 서사 개정)*

v1은 전량 스윕을 `NullSeenIndex`가 `{}`를 흘리면 `should_continue`가 항상 참이 되는 **창발**로 얻었다. 우아했지만 뒷면이 있었다: 동작의 근거가 서로 import도 하지 않는 두 파일의 맞물림에 있어, `should_continue`에 `if not meta: return False` 같은 — 함수명만 보면 완전히 합리적인 — "최적화" 한 줄이 들어오면 OSS 모드가 통째로 죽는다. v2는 전량 스윕을 `FullSweep`이라는 **이름 붙은 값**으로 승격했다. 코드 판독에 원격 추적이 필요 없다.

**진짜 불변식**: v1이 내세운 "분기 0"은 목표가 아니라 부산물이었다. 목표는 **"한쪽만 타는 죽은 경로 0"**이고, `match`의 두 arm은 양쪽 다 탄다:

| 모드 | 프로덕션 | OSS |
|------|---------|-----|
| `Incremental` | 정기 크롤 (30분 cron, MongoSeenIndex) | 저장소 플러그인 장착 시 |
| `FullSweep` | 강제 전량 재크롤 | **기본값** |

죽은 경로가 없으므로 골든 테스트가 양쪽을 덮는다는 v1의 핵심 가치는 그대로다.

**콜드스타트 주의 (여전히 유효)**: `Incremental` + 빈 DB에서도 `meta={}`는 정상이며, 이때 `should_continue`는 True를 반환해야 한다(안 그러면 첫 크롤이 첫 페이지에서 멈춘다). 골든 cold run이 이를 고정하고, `should_continue` docstring과 해당 테스트가 서로를 명시적으로 가리키게 한다. 경계 케이스는 현행과 동일: 상단고정만 있는 페이지는 `all([])==True` → `all_known=True` → break.

부수 효과로 `_process_page_smart`와 `_process_page_full`이 한 함수로 합쳐진다(`meta={}`면 모든 항목이 `previous is None` 분기). 두 함수에 중복된 이미지 검증 + `build_notice` 블록 ~90줄이 목표가 아니라 **결과로** 사라진다.

### 집계 규칙 (현행 카운터와 일치해야 함)

*(v2)* 모든 이벤트는 `accept`에 **균일하게** 흘린다 — v1의 "`ItemSkipped`는 sink 미상담" 특례 폐지 (Mongo ops 무변화, 계약 단순화). 러너의 집계는 sink 반환과 독립:

`NoticeCrawled` → sink 반환값, **sink가 `None`이면 `INSERTED`** · `NoticeUnchanged`/`ItemSkipped` → `skipped` (러너 직접 집계; sink는 보통 무시) · `ItemFailed`/`ListFetchFailed` → `errors` · `PageCompleted` → `sink.flush()` · `SourceFinished` → `source_down`/`last_error`/`duration_ms`.

*(PR 6 구현 addendum)* `ContentRefreshed` → `updated` (outcome 무시 — 현행 백필 계수) · `SourceStarted` → 무집계 · 미지의 이벤트 → accept 후 무집계. 구현은 `core/runner.py::run_events`.

### facade — ~~`core/simple.py`~~ → 구현은 `modules/notices/simple.py` *(v2 신설, adr-006 §⑨)*

```python
async def iter_notices(source, strategy, **kw) -> AsyncIterator[Notice]:
    """공지만 원하는 사용자용. 이벤트 스트림의 필터일 뿐, 별도 구현이 아니다."""
    async for ev in iter_source(source, strategy, **kw):
        if isinstance(ev, NoticeCrawled):
            yield ev.notice
```

크롤 로직 0줄 — `iter_notices`가 깨지려면 `iter_source`가 깨져야 하므로 테스트 부담이 늘지 않는다. "두 번째 경로 금지"가 금지하는 건 로직의 중복이지 진입점의 복수가 아니다. facade의 기본 `max_pages`는 작게 잡는다 — 캐주얼 사용자를 FullSweep 기본 2500페이지로부터 보호.

### 조립 시점 런타임 검증 *(v2 신설, adr-006 §⑩)*

```python
# wiring.py
def build_runtime(...):
    if not isinstance(sink, Sink):       # @runtime_checkable
        raise ConfigError(f"{type(sink).__name__}가 Sink 프로토콜을 충족하지 않음 "
                          f"(prepare/accept/flush 확인)")
```

`flush` 누락이 HTTP 수십 회 뒤 `AttributeError`가 아니라 부팅 시점 명확한 에러가 된다. 한계: `runtime_checkable`은 메서드 **이름 존재만** 검사, 시그니처는 못 본다. 루프가 아니라 조립 지점에 두는 이유: 프로세스당 1회.

### flush 실패 계약 *(v2 신설, adr-006 §⑪)*

**flush 예외는 전파되고 해당 소스의 결과가 탈락한다. 버퍼 재시도 여부는 sink 구현의 책임이다.** — 현행 의미의 명문화(`orchestrator.py:409`의 `bulk_touch` 예외가 페이지 루프 try 밖 → `gather(return_exceptions=True)` → `department_crawl_failed`). 골든 바이트 동일성을 위해 마이그레이션 중엔 이 의미를 유지하고, 소스 내 격리 개선은 1.0 전 재검토 조건.

## Stage — 체인이 아니라 팬아웃

`normalizer.py:96-101`이 `cleanHtml`과 `content`를 **raw HTML에서 각각 독립적으로** 파생한다. 선형 체인으로 엮으면 `clean_html`이 이미 정규화된 문자열을 받아 모든 공지의 `cleanHtml`이 조용히 바뀐다.

```python
@dataclass
class ContentDoc:
    raw: str | None                   # 원본 HTML — 스테이지는 서로가 아니라 이걸 읽는다
    content: str | None = None        # normalize_content_urls(raw)
    clean_html: str | None = None     # clean_html(raw)   <- content가 아니라 raw에서
    text: str | None = None
    markdown: str | None = None
    content_hash: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

class Stage(Protocol):
    name: str
    async def apply(self, doc: ContentDoc, ctx: StageContext) -> ContentDoc: ...
```

코어 기본 체인 (`normalizer.py:96-148` 순서 그대로):
`NormalizeUrls → CleanHtml → VerifyImages(선택) → InjectImageDimensions → SizeGuard(5MB) → ExtractText → ToMarkdown → ContentHash`

- `SizeGuard`는 `clean_html`과 `content`를 **둘 다** null로 만든다 (현행 동작), 그리고 dimension 주입 **이후**에 돌아야 한다 — 측정 대상이 주입된 HTML이므로.
- 중복 상수 정리: `orchestrator.py:_MAX_CONTENT_BYTES`와 `normalizer.py:MAX_CONTENT_BYTES`는 같은 숫자의 두 선언이며 절대 어긋나선 안 된다.
- AI 플러그인은 `SummarizeStage`를 append해 `doc.meta`에 쓴다 — 같은 프로토콜, 서비스 의존.

## 프로파일 — 선택적 설정이 만드는 새 실패 모드

지금은 `MONGO_URL` 누락 = `SystemExit`. 리팩터 후에는 **"mongo 플러그인 없음"이 정당한 지원 상태**다 (그게 목표다). 그래서 `MONGO_URL`을 잃은 배포는 136개 소스를 전량 크롤하고, 상세 페이지를 전부 가져오고, 아무것도 안 쓰고, **깨끗한 성공 로그를 남긴다**. `known-issues.md` §7보다 나쁘다 (§7은 132개 학과를 막았고 이건 136개 전부 + 대역폭까지 태운다).

방어:

- `wiring.build_runtime(settings, profile="production")`이 필수 플러그인 부재 시 **기동 거부**
- 부팅 시 `active_plugins=[mongo,discord,ai,sched]` 1줄 로그 + 09:00 Discord 일일 요약에 포함 → 플러그인 누락이 매일 보임
- 실행당 `crawl_coverage attempted=N enabled=M` 로그 (~5줄). §7이 며칠간 안 보였던 이유가 attempted와 enabled를 아무도 대조하지 않아서였다

## 알려진 한계 *(v2 신설 — 알고 수용한 것들)*

- **`SeenIndex.lookup`은 비스트리밍** — Mongo 구현이 커서를 전부 dict로 물어온다. 페이지당 ~10건이라 현재 무해하나, 배치가 커지면 재검토. 스트리밍 인터페이스로의 변경은 breaking이므로 1.0 전에 판단.
- **이벤트 버퍼링 경고** — `NoticeCrawled`가 최대 5MB `cleanHtml`을 가진 `Notice`를 참조한다. 참조 복사라 발행 비용은 0이지만, sink가 **이벤트 자체를** 리스트에 쌓으면 그만큼 GC가 안 된다. `MongoSink._touches`처럼 필요한 필드만 뽑아 쌓을 것 — sink 작성자 가이드에 명시.
- **async generator 스택 트레이스** — `wiring → runner → iter_source → pipeline → sink.accept`로 호출 깊이가 늘고, 제너레이터 경유 예외는 프레임이 잘려 보일 수 있다. 완화: 이벤트가 자기완결(`source_id` 베이스)이라 "어느 소스에서 났는지"는 이벤트만으로 복원 가능, 러너는 얇게 유지.

## 부록 — 이 설계가 기대는 개념들

리뷰 라운드에서 정리된 용어 지도. 각 개념이 이 설계의 어디에 나타나는지와 함께 — 검색 가능한 자산으로.

| 개념 | 이 설계에서 | 한 줄 |
|------|------------|-------|
| Hexagonal Architecture (Ports & Adapters) | 3-포트 seam 전체 구조 | 비즈니스 로직은 포트만 알고, 어댑터(플러그인)가 포트를 구현한다 |
| Dependency Inversion (SOLID의 D) | 코어가 `MongoSeenIndex`가 아니라 `SeenIndex`에 의존 | 상위·하위 모듈이 둘 다 추상에 의존 |
| Null Object Pattern | `NullSink`/`NullWorkSeed` (존치) · `NullSeenIndex` (스텁 강등) | "없음"을 no-op 객체로. v2 교훈: 동작을 **유도**하는 Null은 창발 위험 |
| Make Illegal States Unrepresentable | `CrawlMode = Incremental(seen) \| FullSweep` | 불법 조합을 검증이 아니라 타입 구조로 차단. 입문은 에세이 "Parse, don't validate" |
| Sum type (tagged union) | `CrawlMode`, `CrawlEvent` | 케이스가 닫힌 대수적 타입 + `match` 전수 검사 |
| Expression Problem | 이벤트 2계층의 배경 딜레마 | 타입 확장과 연산 확장은 동시에 쉬울 수 없다 — 선택만 있다 |
| Tolerant Reader | "sink는 모르는 이벤트를 무시한다" | 소비자가 미지의 것을 견디게 해 생산자의 진화를 허용 |
| Hyrum's Law | 0.x 전략 · 결과 계층 동결 | 사용자가 충분히 많으면 관찰 가능한 모든 동작이 계약이 된다 |
| Contract Test | sink 적합성 스위트 | 인터페이스의 모든 구현이 통과해야 하는 테스트 |
| Characterization (Golden) Test | PR 0의 크롤 골든 | 기존 동작을 스냅샷으로 고정하고 리팩터하는 기법 — Feathers, *Working Effectively with Legacy Code* |
| Facade | `iter_notices()` | 복잡한 하위 API 위의 단순 진입점 — 로직 중복 없이 |
| Structural vs Nominal Typing | Protocol의 런타임 무검증 → `@runtime_checkable` 보강 | 구조적 타이핑은 유연한 만큼 런타임 보장이 없다 |
| YAGNI vs Last Responsible Moment | "지금 정할 것 vs 미룰 것"의 기준 | 공개 후 breaking인 **계약**은 지금, additive한 **기능**은 나중에 |
