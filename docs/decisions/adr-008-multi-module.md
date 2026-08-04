# ADR-008: 두 번째 모듈 — 두 개의 아키타입, 가족 단위 조립, 선택적 실행

- **상태**: 제안됨 (2026-08-04)
- **관련**: [adr-006](adr-006-core-plugin-split.md) (코어/플러그인 분리 — 본 ADR이 그 ⑬을 이어받음), [architecture.md](../architecture.md), [adding-a-module.md](../adding-a-module.md), [sink-authors-guide.md](../sink-authors-guide.md)

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

스냅샷 모듈의 키는 문자열이니 일반화하고 싶어지지만, 이건 rename의 탈을 쓴 **타입 변경**이고 stringify 지점 3곳(`orchestrator.py:314,387`, `policy.py:54`)이 영원히 일치해야 한다. 하나만 놓치면 **예외가 안 난다** — 전 항목이 새 글로 보여 30분마다 13만 건이 재-upsert되고, `crawledAt`이 컬렉션 전체에서 요동치고, 일일 요약의 "24시간 신규" 수치가 무의미해진다. `py/scripts/migrate_oversized_articleno.py`가 있다는 건 이 도메인이 이미 숫자 사고를 한 번 겪었다는 뜻이다.

그리고 **지금 이걸 원하는 소비자가 없다** — bus의 키는 상수다. 재검토 조건은 아래.

### ④ 조립 단위는 모듈이 아니라 **가족(family)**이다

`wiring._FAMILIES`가 가족별로 (모듈 이름들, 필요한 `Config` 속성, 빌더)를 선언한다.

- 이름을 **선언**하는 이유: 게이트가 "이거 돌 수 있나"를 **아무것도 import하기 전에** 답해야 한다. 아니면 "플러그인이 없다"고 거절하려고 그 플러그인을 import해야 한다.
- 선언은 두 번째 진실 원천이므로 `_assert_declaration_matches`가 매 조립마다 실제 빌드 결과와 대조한다. 드리프트는 조용히 안 도는 가족이 아니라 `WiringError`다.
- `requires`가 비면 production은 **거절**, 그 외 환경은 로그 남기고 **스킵**. 남의 API 키가 없는 개발자도 나머지 크롤러는 돌려야 한다.

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
- **`article_no → key: str`** — 학식/학사일정이 실제로 int가 아닌 키를 원할 때. 1.0 이후이므로 2.0을 각오한다(외부 소비자가 없으니 커밋 하나 값이다).
- **가족 3개 초과** — `_FAMILIES`가 선언 테이블 이상으로 자라면 entry-point 발견을 다시 본다(adr-006의 미발동 재검토 조건).
- **스냅샷 아키타입 두 번째 소비자** — 학사일정이 붙을 때 `SnapshotSink`가 해시 비교를 정말 원하는지 본다. 그때 답은 sink가 아니라 **모듈이 `ItemUnchanged`를 emit**하는 쪽일 가능성이 높다.
- **틱 누락이 상시화** — `job_tick_missed`가 꾸준히 나오면 컨테이너 분리(⑦)를 앞당기거나 관용치를 재조정한다.
- **알림 출처가 셋 이상** — `label` 문자열이 부족해지면 웹훅을 가른다.
