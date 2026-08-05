# ADR-008: 두 번째 모듈 — 두 개의 아키타입, 가족 단위 조립, 선택적 실행

- **상태**: 제안됨 (2026-08-04) · **일부 개정됨 (2026-08-05 — bus 모듈 등록, 아래 참조)**
- **관련**: [adr-006](adr-006-core-plugin-split.md) (코어/플러그인 분리 — 본 ADR이 그 ⑬을 이어받음), [architecture.md](../architecture.md), [adding-a-module.md](../adding-a-module.md), [sink-authors-guide.md](../sink-authors-guide.md)

> **2026-08-05 개정 — 세 모듈이 shadow 키로 실제로 돈다.** 설계는 그대로이고, 붙이면서
> 알게 된 것 다섯 가지가 결정을 바꿨거나 값을 매겼다.
>
> **ⓐ bus 가족은 하나가 아니라 둘이다.** `bus`(bus-hssc·bus-jongro)와
> `bus-eta`(bus-campus-eta). ④가 정의한 가족은 "함께 출하되고 함께 설정되는 모듈"인데
> 이 셋은 그렇지 않다 — 자격증명 발급자가 다르고(SKKU+서울 TOPIS vs 네이버 클라우드),
> 주기가 60배 차이나고, 저장 컬렉션도 다르다. 하나로 묶으면 ⑦의 분리 컨테이너가
> `--module bus-hssc,bus-jongro`로 선택하는 그 가족이 campus ETA도 소유하게 되고,
> **네이버 키 만료가 프로덕션 기동 거부**(④)가 되어 셔틀 전광판까지 같이 죽는다.
> `_FAMILIES`는 이제 3개 — 재검토 조건 "가족 3개 초과"에 **도달했고 넘지는 않았다**.
>
> **ⓑ `campus_eta`는 `bus_cache`에 살 수 없다.** 그 컬렉션에는 서버가 만든 TTL
> 인덱스(`ttl_updatedAt`, `_updatedAt` 기준 60초)가 있고 `SnapshotSink`는 매 쓰기마다
> `_updatedAt`을 찍는다. hssc(10초)·jongro(40초)는 창 안쪽이지만 campus ETA의 자연
> 주기는 10분이라 **600초 중 540초 동안 문서가 없다** — 5단계의 shadow-vs-live 비교가
> 읽을 것이 없다. 서버는 이 키를 `bus_cache`에서 읽은 적이 없으므로(온디맨드 계산 +
> 인메모리 캐시) 계약이 아직 없고, 계약이 없을 때만 공짜인 선택을 지금 한다: **자체
> 컬렉션 `campus_eta`, TTL 없음.** `SnapshotSink.prepare`가 인덱스를 만들지 않는 이유를
> 적어둔 그 docstring이 가리키던 "누가 만드는지 의도적으로 정하라"의 첫 사례다.
>
> **ⓒ shadow 플립은 코드 상수다.** `wiring.BUS_SHADOW_WRITES`. 환경변수로 두는 안은
> 대안 표의 `CRAWLER_MODULES` 기각 사유와 같은 이유로 기각 — 무엇이 쓰이는지를 조용히
> 바꾸는 배포 변수는 known-issues §7의 구조다. 커밋 하나가 커트오버이고, 그 커밋은
> 리뷰를 받는다.
>
> **ⓓ ③(`article_no: int → key: str` 연기)의 청구서가 도착했다.** 스냅샷 모듈에는 항목
> 번호가 없어서 `ItemFailed`/`ItemSkipped`에 `article_no=0`을, `ListFetchFailed`에
> `page=0`을 넣는다. `modules/bus/module.NO_ITEM_NUMBER` 한 곳에 모아 눈에 보이게 뒀다.
> 아직 ③을 뒤집을 만큼은 아니다 — 재검토 조건은 "학식/학사일정이 실제로 int가 아닌
> 키를 원할 때"이고, 이건 증거 한 건이지 소비자가 아니다.
>
> **ⓔ 알림 label이 셋이 됐다** (`notices`·`bus`·`bus-eta`). 재검토 조건 "알림 출처가 셋
> 이상 → 웹훅을 가른다"에 도달했다. **의도적으로 미룬다**: 아직 세 label이 한 프로세스에서
> 나오고, ⑦의 컨테이너 분리 전까지는 "어느 컨테이너냐"가 질문이 아니다. 분리와 함께 다시 본다.
>
> **ⓕ 리뷰가 찾은 침묵 셋을 막았다.** ① `run_events` 호출이 무방비였다 — 스트림이나 sink에서
> 예외가 나면 `_on_results`를 건너뛰어 **틱이 up도 down도 아닌 상태**가 된다.
> `consecutiveFailures`가 그대로라 알림이 영영 안 뜨고 일일 요약은 "정상"이라고 말한다. 기록
> 없는 실패보다 기록된 실패가 낫다 — `orchestrator.py`가 같은 이유로 유지하는 그 넓은
> `except Exception`을 `run()`에도 뒀다. ② `read_envelope`는 `headerCd`와 무관하게 body가
> 리스트가 아니면 `NO_DATA`를 준다(TS의 `if (!apiData) return;` 그대로 — 파리티라 못 바꾼다).
> 하지만 **헬스 신호는 헤더 코드로 가른다**: `"4"`는 매일 밤이고 `"0"` + 빈 body는 업스트림이
> 성공을 주장하며 아무것도 안 보낸 것이다. 합치면 영구 고장이 새벽 2시와 구분되지 않는다.
> 쓰기 동작은 양쪽 다 "안 씀"이라 파리티는 그대로다. ③ `EtaData(legs.get("inja"), ...)`는
> `LEGS` 표의 이름이 바뀌면 매 틱 아무것도 안 쓰면서 성공을 보고했다 — `EtaData(**legs)`로
> 바꿔 첫 틱에 `TypeError`가 나게 했다.
>
> ⚠️ **배포 순서 전제.** 컨테이너는 `--module` 없이 `start`를 돌리므로 **모든 가족을 선택**하고,
> production에서 선택된 가족이 미설정이면 스킵이 아니라 **기동 거부**(④)다. 즉 VM의 `.env`에
> 다섯 변수가 **먼저** 들어가야 하며, 아니면 배포가 non-zero로 끝나고 자동 롤백된다.
> `py/.env.example`에 경고와 함께 자리를 만들어 뒀다.
>
> **1.0 게이트는 여전히 닫혀 있다.** adr-006 ⑬의 조건은 "두 번째 모듈이 실제로 돈다"이고,
> 재검토 조건이 그것을 "shadow 키가 아니라 실제 트래픽을 서빙할 때"로 못박아 뒀다.
> 이 개정은 세 모듈을 등록하고 shadow에 쓴다 — 5단계가 커트오버다.

## 맥락

adr-006은 `0.x`로 출하하면서 1.0 게이트를 **"두 번째 모듈이 실제로 프레임워크 위에서 돈다"**에 걸어뒀다 — *"모듈 하나뿐인 프레임워크의 추상화는 검증 안 된 추측이다"*(§⑬). 그 두 번째가 온다: bus(셔틀·종로 실시간), 이어서 학식·학사일정.

bus는 지금 **다른 레포**에 있다. `skkuverse-server`의 전용 `ROLE=poller` 컨테이너가 in-process로 긁는다. 이건 크롤링인데 서빙 코드 옆에 산다 — 옮기는 동기는 **코드 소유권**이지 "같은 프로세스여야 한다"가 아니다.

그리고 옮기려고 코드를 읽으면서 알게 된 사실이 설계를 바꿨다.

## 결정

### ① 코어는 아키타입을 **둘** 지원한다 — 하나로 일반화하지 않는다

bus는 notices와 모양이 다르다. 억지로 같은 틀에 넣는 게 adr-006이 경계한 바로 그 "검증 안 된 추측"이다.

| | notices | bus / 학식 / 학사일정 |
|---|---|---|
| 단위 | 페이지네이션된 글 목록 | 키 하나당 문서 하나 |
| 키 | 소스별 `articleNo: int` | `"hssc"`, 날짜, 연도 |
| 변경 감지 | 항목별 title+date+hash, early-stop | 통째로 교체, 또는 문서 해시 비교 |
| 주기 | cron `*/30` | `interval_seconds` 10~40초 (bus), 일 1회 (학사일정) |
| 상태 | 무상태 | **틱 사이 상태 유지** (체류시간 트래커) |

- **항목 스트림** 아키타입 = 기존 `SeenIndex`/`WorkSeed`/이벤트 tier. notices가 쓴다.
- **스냅샷** 아키타입 = `plugins/mongo/snapshot.SnapshotSink`. `_id = 자연 키`로 문서 통째 upsert. bus·학식·학사일정이 쓴다.

스냅샷 쪽에 **코어 변경은 없다**. 플러그인 하나(≈100줄)면 충분하다는 게 두 아키타입을 따로 두는 실증이다.

### ② result tier는 도메인 중립 이름을 쓴다 (adr-006 개정)

`NoticeCrawled` → `ItemCrawled(item: Any)`, `NoticeUnchanged(article_no, views)` → `ItemUnchanged(article_no, fields)`, `PageCompleted(page)` → `BatchCompleted(index)`, `SourceResult.dept_id/dept_name` → `source_id/source_name`. 상세와 근거는 adr-006의 2026-08-04 개정 노트.

핵심은 이름이 아니라 **삭제된 import**다: `core/events.py`가 달고 있던 `TYPE_CHECKING` 역방향 edge(core → modules). `tests/structure/test_boundaries.py`가 반대 방향으로 금지하는 그 edge다.

**`CrawlItem` Protocol은 기각.** `@runtime_checkable`은 멤버 *존재*만 보고 타입·시그니처를 안 본다(`key`를 property로 두면 `issubclass`는 아예 `TypeError`). 더 결정적으로 `MongoSink`의 `$setOnInsert`/`$push editHistory`는 **필드 분할 정책**이라 "스스로 직렬화하라"로 표현이 안 된다 — 구현체 하나를 보고 만든 Protocol은 `Notice`의 인터페이스에서 이름만 지운 것이다.

### ③ `article_no: int → key: str`은 1.0 이후로 미룬다

스냅샷 모듈의 키는 문자열이니 일반화하고 싶어지지만, 이건 rename의 탈을 쓴 **타입 변경**이고 stringify 지점 3곳(`orchestrator.py`의 lookup 2곳과 `policy.py`의 `has_changed`)이 영원히 일치해야 한다. 하나만 놓치면 **예외가 안 난다** — 전 항목이 새 글로 보여 30분마다 13만 건이 재-upsert되고, `crawledAt`이 컬렉션 전체에서 요동치고, 일일 요약의 "24시간 신규" 수치가 무의미해진다. `py/scripts/migrate_oversized_articleno.py`가 있다는 건 이 도메인이 이미 숫자 사고를 한 번 겪었다는 뜻이다.

그리고 **지금 이걸 원하는 소비자가 없다** — bus의 키는 상수다. 재검토 조건은 아래.

### ④ 조립 단위는 모듈이 아니라 **가족(family)**이다

`wiring._FAMILIES`가 가족별로 (모듈 이름들, 필요한 `Config` 속성, 빌더)를 선언한다.

- 이름을 **선언**하는 이유: 게이트가 "이거 돌 수 있나"를 **아무것도 import하기 전에** 답해야 한다. 아니면 "플러그인이 없다"고 거절하려고 그 플러그인을 import해야 한다.
- 선언은 두 번째 진실 원천이므로 `_assert_declaration_matches`가 매 조립마다 실제 빌드 결과와 대조한다. 드리프트는 조용히 안 도는 가족이 아니라 `WiringError`다.
- `requires`가 **가리키는 `Config` 속성**이 비면 production은 **거절**, 그 외 환경은 로그 남기고 **스킵**. 남의 API 키가 없는 개발자도 나머지 크롤러는 돌려야 한다. 단 선택된 가족이 **전부** 스킵되면 어느 환경이든 거절한다 — 그때는 "나머지"가 없고, 조용히 idle한 컨테이너가 `UnknownModuleError`로 막으려던 바로 그 상태다.
- `requires`에 `Config`에 없는 이름을 적으면 오타이지 설정 누락이 아니므로 `WiringError`. `getattr(..., None)`이면 둘이 구분 안 된다.

### ⑤ 실행할 모듈 선택은 `build_runtime` 한 곳에서

`start --module a,b,c`. 모르는 이름은 유효한 이름들을 나열하며 **에러**다 — 예전 필터는 조용히 매칭 실패라서 `--module notice`(단수)가 잡 0개를 등록하고 컨테이너는 healthy하게 아무것도 안 했다.

스케줄러의 `module_filter`는 **제거**했다. 하류의 두 번째 필터는 상류와 어긋날 수만 있고, 아무것도 매칭 못 하는 이름을 기꺼이 받아준다.

선택이 조립 시점에 있어야 하는 이유가 하나 더 있다: **선택되지 않은 가족은 빌드조차 안 된다**. 그래야 notices 전용 컨테이너가 bus 자격증명 없이 부팅한다(⑦).

### ⑥ 틱 누락은 이름을 갖는다, 그리고 관용 시간은 모듈별이다

`misfire_grace_time`이 `ModuleConfig`로 올라왔다. 숫자 자체는 스케줄러 플러그인에 남는다 — "얼마나 늦으면 늦은 거냐"는 스케줄링 정책이지 모듈 계약이 아니다.

misfire는 **coalesce보다 먼저** 판정된다. 관용 시간을 넘긴 틱은 다음 것과 합쳐지지 않고 통째로 버려진다. 30분 cron에 맞는 관용치가 10초 폴러의 틱을 대부분 삼킨다.

버려진 틱은 원래 **침묵**이었다. `EVENT_JOB_MISSED` 리스너가 `job_tick_missed`로 모듈 이름과 함께 남긴다.

### ⑦ 컨테이너 분리는 배포 결정이지 아키텍처 변경이 아니다

같은 이미지, compose 서비스 둘. `command: start --module ...`로 가른다. 서버의 `ROLE=poller`가 이미 쓰는 패턴이라 운영에 새 개념이 아니다.

프로세스 안에서는 격리가 **불가능**하다: `AsyncIOExecutor`는 네이티브 코루틴을 이벤트 루프에서 직접 돌리고 notices도 bus도 `async def`다. executor를 따로 붙여도 소용없다.

⚠️ bus 컨테이너는 **replica 1개 고정**. 체류시간 상태가 인스턴스 메모리에 있어서 둘로 늘리면 상태가 갈라지고 두 writer가 같은 `_id`를 두고 경쟁한다.

## 대안과 기각 사유

| 대안 | 기각 사유 |
|---|---|
| bus를 `SeenIndex`/`ItemCrawled` 항목 스트림으로 표현 | 키가 상수 하나, 페이지 없음, 항목별 diff 없음. 다섯 타입을 25~50개 파일에서 rename해서 모듈 하나가 그중 하나를 상수값으로 쓰게 하는 일 |
| `CrawlItem` Protocol | ②. 런타임 무검증 + `MongoSink` 필드 분할 정책과 충돌 |
| `SnapshotSink`에 `compare_hash` 옵션 | 변경 감지에는 이전 상태가 필요하고 그게 `SeenIndex`/`ItemUnchanged`다. 조용히 write를 건너뛰는 sink는 러너에게 거짓말도 해야 한다(러너는 `None`을 INSERTED로 읽는다). 필요한 모듈이 생기기 전에 넣는 건 adr-006이 경계한 추측 |
| `CRAWLER_MODULES` 환경변수로 가족 on/off | `CRAWL_SOURCE_FILTER` 사고(known-issues §7)의 재발 구조. 선언이 아니라 **파생**이어야 한다 — `active_plugins`와 같은 원칙 |
| 모듈 테이블을 `core/registry.py`로 | `test_public_api.py::test_settings_and_registry_are_deliberately_not_exported`가 막는다. 그리고 코어가 이 배포판의 모듈 목록을 알 이유가 없다 |
| `ModuleConfig.name`을 Enum으로 | 코어가 닫힌 모듈 목록을 갖게 된다. 대신 wiring 테이블이 SSOT이고 built-vs-declared 단언이 정직성을 지킨다. Enum 키는 값이 진짜 상수인 곳(bus의 `BusSource`/`CacheKey`)에 쓴다 |

## 재검토 조건

- **1.0 태깅** — bus가 shadow 키가 아니라 **실제 트래픽을 서빙**할 때. adr-006 ⑬의 조건은 "두 번째 모듈이 실제로 돈다"이지 "이름을 정리했다"가 아니다.
- **`article_no → key: str`** — 학식/학사일정이 실제로 int가 아닌 키를 원할 때. 1.0 이후이므로 2.0을 각오한다(외부 소비자가 없으니 커밋 하나 값이다). *(2026-08-05: 증거 1건 도착 — 개정 ⓓ. 아직 미발동, 소비자가 아니라 비용이다.)*
- **가족 3개 초과** — `_FAMILIES`가 선언 테이블 이상으로 자라면 entry-point 발견을 다시 본다(adr-006의 미발동 재검토 조건). *(2026-08-05: 정확히 3개 — 도달, 미초과. 네 번째가 조건이다.)*
- **스냅샷 아키타입 두 번째 소비자** — 학사일정이 붙을 때 `SnapshotSink`가 해시 비교를 정말 원하는지 본다. 그때 답은 sink가 아니라 **모듈이 `ItemUnchanged`를 emit**하는 쪽일 가능성이 높다. *(2026-08-05: bus가 첫 소비자. 해시 비교를 원하지 않았다 — 실시간 데이터는 매 틱 다르다.)*
- **틱 누락이 상시화** — `job_tick_missed`가 꾸준히 나오면 컨테이너 분리(⑦)를 앞당기거나 관용치를 재조정한다. *(2026-08-05: 이제 관측 가능해졌다. 10초 폴러가 notices 크롤과 이벤트 루프를 공유하는 상태가 5단계까지 지속된다.)*
- **알림 출처가 셋 이상** — `label` 문자열이 부족해지면 웹훅을 가른다. *(2026-08-05: 셋 도달 — 개정 ⓔ. 한 프로세스에 있는 동안은 미룬다.)*
- **`MONGO_CACHE_COLLECTION`이 실제로 설정될 때** *(2026-08-05 신설)* — 크롤러는 `bus_cache`를 하드코딩한다. 서버는 이 오버라이드를 지원하지만 어느 배포도 설정하지 않고 `.env.example`이 기본값으로 고정해 뒀다. 누가 설정하는 순간 크롤러는 **아무도 읽지 않는 컬렉션에 조용히 쓴다** — 그때는 `Config` 필드를 하나 만든다.
