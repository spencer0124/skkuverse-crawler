# 새 모듈 추가하기

크롤 모듈 하나를 처음부터 붙이는 절차. 설계 근거는 [adr-006](decisions/adr-006-core-plugin-split.md)(코어/플러그인 분리)과 [adr-008](decisions/adr-008-multi-module.md)(두 아키타입·가족 조립), 현재 코드 배치는 [architecture.md](architecture.md).

## 0. 어느 아키타입인가

먼저 이것부터 정한다. 잘못 고르면 나중에 전부 다시 쓴다.

| | **항목 스트림** | **스냅샷** |
|---|---|---|
| 언제 | 페이지네이션된 목록에서 항목을 하나씩 긁고, 이미 본 건 건너뛰고 싶다 | 키 하나당 문서 하나를 통째로 교체한다 |
| 예 | notices | bus 실시간, 학식(날짜별), 학사일정(연도별) |
| 쓰는 것 | `SeenIndex`·`WorkSeed`·`Incremental`/`FullSweep`·`ItemUnchanged` | `plugins/mongo/snapshot.SnapshotSink` |
| 저장 | 모듈 전용 sink (notices의 `MongoSink`처럼) | `SnapshotSink` 그대로 |

애매하면 스냅샷으로 시작한다. 항목 스트림 기계장치는 "이미 본 항목을 다시 fetch하지 않는 것"이 실제로 이득일 때만 값을 한다.

## 1. 디렉터리

```
py/src/skkuverse_crawler/modules/<name>/
  __init__.py
  module.py      CrawlModule 구현
  cli.py         click 커맨드 (선택)
  models.py      frozen dataclass
  <fetchers>/    순수 파싱 + httpx 클라이언트
```

**규칙 셋. 전부 테스트가 강제한다.**

1. **`modules/`는 `plugins/`를 import하지 않는다** (`tests/structure/test_boundaries.py`). 함수 안 지연 import도 잡힌다. 저장은 주입받는다.
2. **`shared/db.py`도 import하지 않는다** (`test_extras_isolation.py`의 `ADAPTERS`). 모듈은 mongo extra 없이 import돼야 한다.
3. **`os.environ`을 읽지 않는다** (`test_env_is_the_only_environment_reader`). 설정은 `Config`로 온다. 패키지 데이터는 `importlib.resources`로 읽는다 — `SOURCES_JSON_PATH` 같은 예외는 컨테이너가 파일을 mount하기 때문이지 기본값이 아니다.

## 2. `CrawlModule` 구현

```python
class MyModule:
    def __init__(self, *, sink: Sink) -> None:      # 주입, 절대 self-fetch 금지
        self._sink = sink
        self._prev: Mapping[str, Any] = {}          # 틱 사이 상태는 인스턴스에

    @property
    def config(self) -> ModuleConfig:
        return ModuleConfig(
            name="my-module",
            interval_seconds=60,          # 또는 cron_schedule
            misfire_grace_time=5,         # 빠른 주기면 반드시 조정 (§5)
        )

    async def run(self, **kwargs: Any) -> dict: ...
    async def shutdown(self) -> None: ...
```

APScheduler는 **같은 인스턴스**를 계속 부르므로 인스턴스 상태는 틱 사이에 살아남는다. 그 상태를 다루는 순수 함수는 `self`를 읽지 말고 인자로 받아라:

```python
items, self._prev = normalize(self._prev, raw, now=...)
```

이래야 캡처된 픽스처로 시계도 네트워크도 없이 결정론적으로 재생할 수 있다.

## 3. 이벤트 emit

```python
yield ItemCrawled(source_id="my-source", item=snapshot)
```

`item`은 의도적으로 **타입이 없다**(`Any`). 코어는 어떤 모듈의 스키마도 모른다. 결과는 [sink-authors-guide.md](sink-authors-guide.md)에 정리돼 있고, 특히 **class pattern에서 없는 키워드를 쓰면 예외가 아니라 그냥 매칭 실패**라는 함정을 먼저 읽어라.

`SnapshotSink`가 받는 item은 `.key: str`(문서 `_id`)와 `.fields: Mapping`(그대로 `$set`에 병합) 둘을 가지면 된다. `_updatedAt`은 sink가 찍는다.

⚠️ **대상 컬렉션의 인덱스를 누가 소유하는지 명시적으로 정하라.** `SnapshotSink.prepare`는 아무 인덱스도 만들지 않는다 — 키가 곧 `_id`라 sink 자신은 필요 없기 때문이지, "이 컬렉션엔 인덱스가 필요 없다"는 뜻이 아니다. 남이 만든 TTL 인덱스가 당신 문서를 조용히 지배할 수 있다: bus가 정확히 그 사례로, `bus_cache`의 `_updatedAt` TTL이 60초여서 주기 600초인 campus ETA는 그 컬렉션에 살 수 없었다(문서가 10분 중 9분 부재). 새 컬렉션을 쓰기로 했다면 **소비자가 생기기 전에** 정하라 — 계약이 없을 때만 공짜다.

## 4. `wiring.py`에 가족 등록

```python
def _build_mine(settings: Config, notifier: Notifier) -> tuple[CrawlModule, ...]:
    from .plugins.mongo.snapshot import SnapshotSink
    ...

_FAMILIES = (
    ...,
    ModuleFamily(
        name="mine",
        module_names=("my-module",),          # config.name과 정확히 일치해야 함
        requires=("my_api_key",),             # Config 속성 이름
        build=_build_mine,
    ),
)
```

이름을 여기 **선언**하는 이유: 부팅 게이트가 "이 가족이 돌 수 있나"를 아무것도 import하기 전에 답해야 한다. 선언과 실제 빌드 결과가 어긋나면 `_assert_declaration_matches`가 `WiringError`를 던진다 — 조용히 안 도는 가족보다 낫다.

`requires`가 **가리키는 `Config` 속성**이 비어 있으면 production은 부팅을 거절하고, 다른 환경은 `module_family_skipped` 로그를 남기고 넘어간다. `requires=()`(요구사항 없음)는 항상 통과한다 — notices 가족이 그렇다. 그리고 선택된 가족이 **전부** 스킵돼 돌 게 하나도 안 남으면 환경과 무관하게 거절한다: 그때는 "나머지 크롤러"라는 게 없다.

## 5. 주기와 틱 관용 시간

misfire는 **coalesce보다 먼저** 판정된다. 관용 시간을 넘긴 틱은 다음 것과 합쳐지지 않고 버려진다. 기본값은 `plugins/scheduler/runner.DEFAULT_MISFIRE_GRACE_SECONDS`(10초)라서 30분 cron에는 맞지만 10초 폴러에는 **대부분의 틱을 삼킨다**.

버려진 틱은 `job_tick_missed` 경고로 남는다. 새 모듈을 붙이고 이게 꾸준히 보이면 이벤트 루프를 공유하는 다른 모듈이 블로킹 중이거나, 관용치가 주기에 비해 크다.

## 6. 설정 추가

`core/settings.Config`에 필드를 붙이되 **반드시 기본값과 함께, 맨 아래에**. `Config`는 frozen이고 위쪽 필드에는 기본값이 없으며 `tests/test_wiring.py`가 전체 kwargs로 생성한다 — 기본값 없는 필드를 추가하면 전부 깨진다.

`env.py`가 읽는다. 그게 `os.environ`을 만지는 유일한 곳이다.

## 7. 헬스 리포팅

`SourceResult`를 돌려주면 공짜로 얻는 것:

```python
on_results=functools.partial(record_and_alert, notifier=notifier,
                             threshold=18, label="mine")
```

`threshold`를 **주기에 맞춰라**. `THRESHOLD = 3`은 30분 크롤엔 90분이지만 10초 폴러엔 30초다 — 그대로 두면 첫 깜빡임에 Discord가 울린다.

일일 09:00 요약에 끼려면 `plugins/health/probes.py`에 `CoverageProbe`를 추가하고 wiring에서 넘긴다.

## 8. CLI (선택)

`cli.py`의 `_LAZY`에 한 줄. help 문자열은 커맨드 docstring과 **정확히** 같아야 한다(`tests/cli/test_lazy_group.py`). extras가 필요하면 `_EXTRA_MARKER`에도 등록 — `test_packaging.py`가 대조한다.

## 9. 체크리스트

- [ ] 아키타입을 골랐다 (§0)
- [ ] `modules/<name>/`이 `plugins/`·`shared.db`·`os.environ`을 안 건드린다
- [ ] 틱 사이 상태는 인스턴스에, 그 로직은 인자를 받는 순수 함수로
- [ ] `ModuleConfig.misfire_grace_time`을 주기에 맞게 정했다
- [ ] `_FAMILIES` 항목의 `module_names`가 `config.name`과 일치한다
- [ ] `Config` 새 필드는 기본값과 함께 맨 아래
- [ ] `record_and_alert`의 `threshold`/`label`을 정했다
- [ ] `ruff check src/` · `mypy src/` · `pytest tests/` 초록
- [ ] 실제 캡처로 파서를 검증했다 (합성 픽스처만으로는 부족하다)
