# ADR-006: 코어/플러그인 분리 — 무상태 코어 + 3-포트 seam + 단일 배포물 extras

- **상태**: 제안됨 (2026-07-30 최초 · 같은 날 설계 리뷰 라운드 후 v2 개정 — 근거 ⑦~⑬)
- **관련**: [core-plugin-architecture.md](../core-plugin-architecture.md) (설계), [core-plugin-plan.md](../core-plugin-plan.md) (단계별 계획), `docs/known-issues.md` §7(침묵 차단 인시던트 — 본 ADR 위험 ⑤의 원형)

## 맥락

크롤러를 오픈소스로 공개하려 한다. 그런데 지금은 **인프라 없이는 아무것도 못 돈다**:

- `shared/config.py:117-120` — `MONGO_URL` 없으면 `SystemExit(1)`. `get_config()`(L126-130)가 지연 초기화라 `configure_logging()`을 포함한 어떤 깊은 호출 지점에서도 프로세스가 죽는다.
- `orchestrator.py:87` — `run_crawl()`이 HTTP 한 번 하기 전에 Mongo 커넥션을 연다.
- `orchestrator.py:246` — **페이지 루프 한가운데서** Mongo를 질의해 상세 페이지를 가져올지 결정하고, `:249-258`이 그 답으로 루프를 끊는다. DB가 없으면 dedup도 early-stop도 없어 136개 소스를 30분마다 100페이지 전량 훑는다.

즉 결합은 "데이터가 어디 저장되냐"에 그치지 않고 **크롤 결정 로직 자체**에 박혀 있다.

게다가 프레임워크가 인프라를 새고 있어서 모듈이 늘 때마다 문제가 복제된다. `feat/schedule-crawler`(`8ad3e8e`)의 학사일정 모듈은 동일 패턴을 그대로 반복한다 — `crawl_schedule()` 첫 줄의 `get_db()`, 자체 `COLLECTION_NAME`, 자체 Mongo `repository.py`. 모듈은 앞으로 더 늘어난다. **프레임워크에서 한 번 끊는 것**이 이 작업의 요점이다.

목표 상태: `pip install skkuverse-crawler` → env·DB·웹훅·AI 서비스 없이 SKKU 게시판을 stdout으로 크롤. 프로덕션은 extras 설치 + 플러그인 조립으로 **현행 동작 그대로** 유지.

**v2 개정 (같은 날, 구현 착수 전)** — 설계 리뷰 라운드에서 v1의 실약점이 드러났다: ⓐ 전량 스윕이 서로 import도 하지 않는 두 파일의 우연한 맞물림으로 창발(§⑦) ⓑ `incremental` bool × seen 구현의 4조합 상태 공간과 잠복 `UnboundLocalError`(§⑦) ⓒ 이벤트 유니온이 확장에 닫힘 — 이벤트 하나 추가가 모든 서드파티 sink에 breaking change(§⑧) ⓓ Protocol의 런타임 무검증(§⑩). 이에 결정 ②·③을 개정하고 ⑥~⑨를 추가했다. 초기안이 무엇이었고 왜 바뀌었는지는 근거 ⑦~⑬에 전부 보존한다. 리뷰가 제안한 종합안 중 **2건은 코드 실측으로 기각**했다(§⑪·⑫) — 설계 논쟁의 승자는 더 우아한 쪽이 아니라 `orchestrator.py` 실물과 맞는 쪽이다.

## 결정

1. **3층 + 리프 3개** — `core/`(인프라 0) · `modules/{notices,schedule,…}`(크롤 로직만) · `plugins/{mongo,health,discord,ai_summary,dispatch,scheduler}`. 조립부는 패키지가 아니라 리프 모듈 3개: `env.py`(os.environ을 만지는 **유일한** 파일) · `wiring.py`(plugins를 import하는 **유일한** 파일) · `cli.py`.
2. **코어는 상태 저장소를 갖지 않는다** — SQLite조차 넣지 않는다. **3개 포트**를 노출한다: `SeenIndex`(읽기: 무엇을 봤나) · `WorkSeed`(저장소가 크롤에 작업을 주입: `find_null_content`) · `Sink`(쓰기, `flush()` 포함). 현행 증분 동작은 통째로 Mongo 플러그인 몫. *(v2 개정)* 증분/전량은 bool 플래그가 아니라 **합 타입** `CrawlMode = Incremental(seen: SeenIndex) | FullSweep` — "증분인데 seen 없음"이라는 불법 상태가 표현 자체가 안 된다. `NullSeenIndex`는 "동작 유도 장치"에서 **테스트 스텁으로 강등**(§⑦). `WorkSeed`는 mode와 **직교** 파라미터 — 전량 재크롤도 백필을 수행한다(§⑫).
3. **크롤 루프는 `AsyncIterator[CrawlEvent]`** — `Notice`를 흘리지 않는다. `run_source()`가 이벤트를 sink에 먹이고 `SourceResult`로 집계한다. *(v2 개정)* 이벤트는 **2계층**: 결과 계층(안정 API — 추가·변경 = major)과 진행 계층(minor에서 추가 가능). 베이스 `CrawlEvent(source_id)`로 모든 이벤트가 자기완결. sink는 모르는 이벤트를 조용히 무시한다 — 이 계약은 문서가 아니라 **contract test**로 강제(§⑧).
4. **콘텐츠 정제(clean_html → cleanMarkdown → contentHash)는 코어, 기본 on, 비활성화 가능.** 단 선형 체인이 아니라 `ContentDoc` 레코드에 대한 팬아웃 (§④). AI 요약은 같은 `Stage` 모양이되 서비스 의존이라 플러그인.
5. **단일 배포물 + extras** — `skkuverse-crawler[mongo,discord,ai,sched]`. 플러그인 코드는 wheel에 들어가되 의존성만 optional.
6. *(v2 신규)* **캐주얼 API는 facade** — `core/simple.py`의 `iter_notices()`. 이벤트 스트림의 4줄 필터, 크롤 로직 중복 0 (§⑨).
7. *(v2 신규)* **Sink 런타임 검증** — `@runtime_checkable` + `wiring.build_runtime`에서 `isinstance` 1회. 서드파티의 `flush` 누락이 첫 페이지 뒤 `AttributeError`가 아니라 부팅 시점 명확한 에러가 된다 (§⑩).
8. *(v2 신규)* **flush 실패 계약 = 현행 의미 명문화** — flush 예외는 전파되어 해당 소스의 결과가 탈락한다. 소스 내 격리 개선은 재검토 조건 (§⑪).
9. *(v2 신규)* **0.x로 공개** — README에 "1.0 전 이벤트 스키마는 minor에서 변경 가능" 명시. **1.0은 `schedule` 모듈이 실제로 프레임워크 위에 올라간 뒤에만** — 모듈 하나뿐인 프레임워크의 추상화는 검증 안 된 추측이다 (§⑬).

## 근거

### ① 코어의 상태 저장소 — 무상태 채택

| 후보 | 판단 |
|------|------|
| ① 코어에 stdlib `sqlite3` 저장소 탑재 | "서비스 불필요 = 요구사항 충족"이라 매력적이지만, **프로덕션이 절대 타지 않는 세 번째 코드 경로**가 생긴다. 아무도 실행하지 않는 경로는 썩는다 (기각) |
| ② JSONL 추가 저장소 | 위와 동일 문제 + seen 조회가 전체 파일 스캔 |
| **③ 무상태 + 포트 (채택)** | 코어에 상태가 없어도 전량 스윕은 성립하고, 증분은 저장소 플러그인이 `SeenIndex`로 공급한다. 프로덕션과 OSS가 같은 코드를 타므로 골든 테스트 하나가 양쪽을 덮는다. *(v2 주석: v1은 이 "같은 코드"를 `NullSeenIndex`의 `{}` 반환이 만드는 **창발**로 얻었는데, 그 메커니즘은 §⑦에서 `FullSweep` 명명 모드로 개정됐다. 결론 — 무상태 코어 — 은 그대로다)* |

이 선택의 강제 조항 *(v2에서 정련)*: 금지되는 것은 분기 자체가 아니라 **한쪽(프로덕션 또는 OSS)만 타는 죽은 경로**다. v1의 "분기 0"은 목표가 아니라 부산물이었고, `match mode:`의 두 arm은 양쪽 다 탄다 — Incremental은 프로덕션 정기 크롤과 저장소를 붙인 OSS가, FullSweep은 프로덕션 강제 재크롤과 OSS 기본이 (§⑦).

### ② 포트를 3개로 쪼갠 이유

읽기/쓰기 2개로 묶으면 `find_null_content`가 어디에도 안 맞는다 — 그건 조회도 저장도 아니고 **저장소가 크롤에 작업을 주입하는** 행위다. 자리를 안 주면 코어로 다시 밀항한다. 실제로 이 한 개 때문에 "결국 코어에 DB가 필요하네"라는 결론에 도달하기 쉽다.

`Sink.flush()`도 선택이 아니다. 현행 `bulk_touch_notices`는 페이지 단위로 모아 `bulk_write(ordered=False)` 한 번을 쏜다. flush 없는 이벤트별 sink는 이걸 페이지당 N회 왕복으로 조용히 퇴화시킨다 (136 소스 × 30분마다).

### ③ 이벤트 스트림 vs `AsyncIterator[Notice]`

| 후보 | 판단 |
|------|------|
| `-> list[Notice]` | 비증분 스윕이 2500페이지 × ~10건 × 최대 5MB `cleanHtml`. 메모리 무제한, 스트리밍 불가 (기각) |
| 콜백/emitter를 1차 API로 | 제어 역전. "콜백이 던진 예외가 내 크롤을 중단시키나?"가 모호하고 `async for`를 원하는 OSS 사용자에게 적대적 (기각) |
| `AsyncIterator[Notice]` | 가장 자연스러워 보이지만 **틀렸다**. "이미 봤고 안 바뀜 → 상세 미조회" 케이스에는 `Notice`가 없다 (안 가져오는 게 최적화의 전부). 흘릴 게 없으니 `bulk_touch_notices`가 표현 불가능해지고, **아무 에러 없이 사라진다** — 카운터는 정상, `crawledAt`만 136개 소스에서 조용히 멈춤 (기각) |
| **`AsyncIterator[CrawlEvent]` (채택)** | `NoticeUnchanged`를 1급 이벤트로 만들어 위 실패 모드를 구조적으로 차단. *(v2: 유니온의 확장 정책은 §⑧에서 2계층으로 개정)* |

### ④ 콘텐츠 정제 — 코어이되 팬아웃

기획 단계 스케치는 선형 체인(`NormalizeUrls → CleanHtml → …`)이었으나 **실코드가 그렇지 않다.** `normalizer.py:96-101`:

```python
cleaned     = clean_html(detail.content, base_url)              # RAW에서
raw_content = normalize_content_urls(detail.content, base_url)  # 역시 RAW에서, 병렬로
```

`cleanHtml`과 `content`는 같은 raw HTML의 **독립 파생**이다. 체인으로 엮으면 `clean_html`이 이미 정규화된 문자열을 받아 **모든 공지의 `cleanHtml`이 조용히 바뀐다**. 따라서 Stage는 문자열이 아니라 이름 있는 슬롯을 가진 `ContentDoc` 레코드 위에서 동작한다 (설계 문서 §Stage).

"코어에 두되 끌 수 있게"를 택한 이유: nh3·markdownify는 **순수 휠**이라 서비스도 설정도 요구하지 않는다. "코어는 아무것도 요구하지 않는다"는 *외부 서비스와 설정*의 부재를 뜻하지 의존성 0을 뜻하지 않는다. 그리고 한국 대학 게시판 raw HTML은 정제 없이는 쓸 수 없으므로 정제 결과가 곧 이 크롤러의 산출물이다.

### ⑤ 배포 형태

| 후보 | 판단 |
|------|------|
| 다중 배포물 (`skkucrawl-core`/`-mongo`/…) | 경계가 가장 단단(코어가 플러그인을 import조차 못 함)하지만 릴리스 기계(버전 정합·CI 매트릭스·N개 pyproject)가 지금 규모에 과함 |
| 퍼블릭 코어 레포 분리 | 외부 기여자 서사는 최고이나 첫날부터 2개 레포 + 릴리스 케이던스 유지 부담 |
| **단일 배포물 + extras (채택)** | 되돌리기 쉬움. 경계는 AST 레이어링 테스트(`modules/**`는 `plugins/`를 import 금지)로 강제 |

### ⑥ 모듈은 `modules/` 아래로 (top-level 아님)

이 리팩터가 원상복귀하지 않게 막는 유일한 장치는 "`modules/`는 `plugins/`를 import하지 않는다, `core/`는 `modules/`를 import하지 않는다"는 불변식이다. `modules/` 패키지가 있으면 **경로 접두사 규칙 한 줄**로 AST 테스트가 강제한다. `notices/`·`schedule/`·`library/`가 최상위 형제로 흩어지면 규칙이 **손으로 관리하는 이름 목록**이 되고, 새 모듈을 추가할 때 갱신을 잊는다. 규칙이 유지보수 비용을 가지면 안 된다.

부수 효과로 현행 `modules/base.py`·`registry.py`는 그 이름을 비워야 하며, 어차피 `core/module.py`·`core/registry.py`가 제 자리다 (모듈 프로토콜은 코어 관심사).

캘린더 모듈 이름은 `8ad3e8e`를 따라 `schedule/`. `calendar`는 stdlib 이름을 가려 얻는 것 없이 코드 리뷰 지뢰가 된다.

---

*이하 ⑦~⑬은 v2 개정분 — 설계 리뷰 라운드가 찾은 문제, 초기안, 개정안을 그대로 보존한다. 각 절의 괄호 병기는 해당 결정이 기대는 개념의 정식 명칭이다 (개념 정의는 설계 문서 부록 참조).*

### ⑦ 크롤 모드 — bool 플래그 + Null 객체 (최초 채택) → `CrawlMode` 합 타입 (개정) *(make illegal states unrepresentable · sum type · null object pattern)*

**최초안 (v1)**: `CrawlOptions.incremental: bool` + 기본 인자 `seen=NullSeenIndex()`. `NullSeenIndex.lookup`이 `{}`를 반환하면 `should_continue(items, {})`가 항상 참 → early-stop이 발동 안 함 → 전량 스윕이 **창발적으로** 성립. "분기 추가 0"을 장점으로 내세웠다.

**리뷰가 찾은 문제 4건**:

1. **창발적 동작의 원격 취약성.** `NullSeenIndex`와 `should_continue`는 서로 import하지 않고, "빈 매핑 → 전량 스윕"이라는 계약이 코드 어디에도 명시돼 있지 않다. 6개월 뒤 누군가 `should_continue`에 `if not meta: return False`라는 — 함수명과 시그니처만 보면 완전히 합리적인 — "최적화"를 넣으면 OSS 모드가 첫 페이지에서 즉시 중단된다. 연결고리가 테스트에만 있다.
2. **상태 공간의 곱.** incremental{True,False} × seen{Mongo,Null} = 4조합인데 "경로가 하나"라고 주장하고 있었다.
3. **잠복 `UnboundLocalError`.** 루프의 `else` 분기(비증분)에서 `all_known`이 대입되지 않는데 아래 `if options.incremental and is_first and all_known:`이 참조한다. `and` 단락 평가로만 보호 — 누가 조건 순서를 `if is_first and all_known and ...`로 바꾸면 비증분 모드에서만 터지고, 프로덕션 정기 크롤로는 재현이 안 된다.
4. **원칙의 자기모순.** "`if seen is None:` 지름길 금지"를 못 박아놓고 정작 `if options.incremental:`이라는 같은 성질의 분기를 남겨뒀다.

**개정안 (v2 채택)**:

```python
@dataclass(frozen=True)
class Incremental:
    seen: SeenIndex          # Null 불가 — 진짜 인덱스 없이는 생성 자체가 안 됨

@dataclass(frozen=True)
class FullSweep:
    pass                     # 상태를 참조하지 않는다

CrawlMode = Incremental | FullSweep
```

- "증분인데 seen 없음"이 **표현 불가능** — 4조합이 2조합으로 줄어든 게 아니라 불법 조합이 타입에서 소멸.
- 전량 스윕이 창발이 아니라 **이름 붙은 값** — 판독에 두 파일 간 원격 추적이 필요 없다.
- `case FullSweep(): meta, all_known = {}, False` 명시 대입으로 잠복 버그 3번이 구조적으로 소멸.
- **부수 이득 — 기본값이 정직해진다**: `Incremental`은 seen 없이 생성이 안 되므로 API 기본값은 `FullSweep`일 수밖에 없다. v1의 기본값(`incremental=True` + `NullSeenIndex`)은 "증분"이라 선언하고 몰래 전량 스윕하는 거짓말이었다.
- `NullSeenIndex`는 삭제가 아니라 **테스트 스텁으로 강등** — 동작을 만들어내는 장치가 아니게 됐으므로 창발성 문제가 소멸.
- 잔여 주의: Incremental + 빈 DB(콜드스타트)에서도 `meta={}`는 정상이며 `should_continue`는 True여야 한다. `if not meta` 최적화 금지는 여전히 유효 — 양방향 docstring 상호 참조 + 골든 cold run이 고정한다.

### ⑧ 이벤트 확장 정책 — 전면 엄격 (최초) → 결과/진행 2계층 + 무시 계약 (개정) *(expression problem · tolerant reader · Hyrum's Law · contract test)*

**최초안 (v1)**: 단일 유니온 + `assert_never` 전면 엄격.

**문제**: 유니온은 "케이스 고정 / 처리기 확장"에 최적인 구조다 (expression problem — 완전한 해법이 없고 트레이드오프 선택만 있음이 알려진 딜레마). 그런데 이 크롤러는 이벤트가 늘 전망이다(첨부·이미지·schedule 고유 이벤트). 이벤트 하나 추가 = 세상 모든 sink의 `match` 갱신 = breaking change. 내부 sink는 mypy가 잡아주지만 이미 배포된 서드파티 sink는 조용히 무시하거나 터진다. 오픈소스 공개 순간 Hyrum's Law가 적용된다 — 관찰 가능한 모든 동작(이벤트 순서, 필드, 예외 타입)에 누군가는 의존하게 된다.

**개정안 (v2 채택)**: 이벤트를 2계층으로 가른다.

| 계층 | 이벤트 | 버전 정책 |
|------|--------|----------|
| **결과** (안정 API) | `NoticeCrawled` · `NoticeUnchanged` · `ContentRefreshed` · `ItemFailed` · `ItemSkipped` | 추가·변경 = **major** |
| **진행** | `SourceStarted` · `PageCompleted` · `ListFetchFailed` · `SourceFinished` | **minor**에서 추가 가능 |

- 계약: **"sink는 모르는 이벤트를 조용히 무시한다"** (`case _: return None`). 문서가 아니라 **contract test**로 강제 — 미지의 이벤트를 `accept`에 넣어 `None` 반환을 확인하는 스위트를 서드파티 sink 작성자에게 제공.
- 내부 sink는 여전히 `assert_never`로 엄격 — 모순이 아니다. 내부는 릴리스와 함께 갱신되므로 엄격함이 안전망이고, 외부는 갱신 시점을 통제 못 하므로 관대함이 안전망이다.
- 러너가 진행 이벤트의 의미(`PageCompleted`→flush 등)를 소유하므로 sink는 결과 계층만 알면 충분하다.
- `source_id`를 베이스 클래스로 — v1은 일부 이벤트에만 있어 sink가 `SourceStarted`를 기억해야 했다(= sink에 상태 발생 = 병렬 크롤에서 위험). 이벤트는 자기완결적이어야 sink가 무상태로 남는다.
- v1의 "`ItemSkipped`는 sink 미상담" 특례 폐지 — 모든 이벤트를 `accept`에 균일하게 흘리고(러너 집계는 독립) sink가 무시한다. Mongo ops 무변화, 계약은 단순해짐.

### ⑨ 캐주얼 API — 이벤트 스트림 단일 표면 (최초) → facade 추가 (개정) *(facade pattern)*

**문제**: 대부분의 사용자는 `NoticeCrawled`만 원한다. 매번 `isinstance` 필터를 강요하는 API는 README 첫 예제 실격.

**개정**: `core/simple.py`의 `iter_notices()` — 이벤트 스트림의 4줄 필터. "두 번째 경로 금지"가 진짜 금지하는 건 **로직의 중복**이지 진입점의 복수가 아니다 — `iter_notices`가 깨지려면 `iter_source`가 깨져야 하므로 테스트 부담이 늘지 않는다. facade의 기본 `max_pages`는 작게 잡는다 (FullSweep 기본 2500페이지로부터 캐주얼 사용자 보호).

### ⑩ 런타임 검증 — Protocol만 (최초) → `@runtime_checkable` + 조립 검사 (개정) *(structural vs nominal typing)*

**문제**: Protocol은 mypy 전용이고, 서드파티 sink 작성자가 mypy를 돌린다는 보장이 없다. `flush`를 빼먹은 sink는 HTTP 요청 수십 회 뒤 첫 페이지 끝에서 `AttributeError`로 터진다.

**개정**: `@runtime_checkable` + `wiring.build_runtime`에서 `isinstance` 1회 검사 → 부팅 시점 명확한 에러. 한계도 명시한다: `runtime_checkable`은 **메서드 이름의 존재만** 보고 시그니처는 못 본다. 검사를 크롤 루프가 아니라 조립 지점에 두는 이유: 루프면 매 이벤트마다, 조립이면 프로세스당 1회.

ABC 상속안(인스턴스 생성 즉시 실패)도 검토했으나 기각 — Protocol을 유지하는 이유(코어가 플러그인 타입을 모름)가 sink에도 그대로 적용되고, 조립 검사로 실용적 안전은 충분하다.

### ⑪ flush 실패 계약 — 미정의 (최초) → 현행 의미 명문화 (개정 · **종합안에서 이탈**)

**문제**: `bulk_write`가 터지면 `_touches`를 재시도할지 버릴지가 계약에 없었다. 미정의가 최악이다.

**리뷰 종합안**: "flush 예외 → 러너가 `ItemFailed`로 집계하고 다음 소스 진행" — **기각.** 코드 실측: 현행 `bulk_touch_notices` 예외는 페이지 루프 try 밖(`orchestrator.py:409`)이라 그대로 전파 → `run_crawl`의 `gather(return_exceptions=True)` → `department_crawl_failed` 로그, 해당 소스 결과 탈락. 마이그레이션 제1 원칙이 골든 바이트 동일성이므로 **현행 의미를 계약으로 채택**한다: "flush 예외는 전파되고 해당 소스의 결과가 탈락한다. 버퍼 재시도는 sink 구현 책임." 소스 내 격리(부분 실패 시 계속) 개선은 1.0 전 재검토 조건.

### ⑫ WorkSeed 위치 — 종합안(Incremental 내부)에서 이탈, 직교 파라미터 유지

**리뷰 종합안**: `WorkSeed`를 `Incremental` 안에 넣고 `FullSweep`에는 두지 않는다 — **기각.** 코드 실측: `orchestrator.py:180`의 null-content 백필은 `options.incremental`과 **무관하게 무조건** 페이지 루프 전에 실행된다. 종합안대로면 프로덕션 전량 재크롤에서 백필 쿼리가 사라져 골든 바이트 동일성 위반.

교훈으로 기록: "FullSweep + WorkSeed"는 불법 상태가 아니라 **현행 프로덕션 동작**이다. make illegal states unrepresentable은 진짜 불법 상태에만 적용해야 한다 — 실재하는 조합을 타입으로 금지하면 그게 버그다.

### ⑬ 복잡도 정당성 — 반론과 조건부 수용

**반론 (리뷰 라운드)**: 신규 기여자가 익힐 개념이 4개다(3-포트 seam / 이벤트 유니온 / Stage 파이프라인 / wiring 조립). 현행은 `orchestrator.py` 한 파일을 위에서 아래로 읽으면 끝난다. 이 리팩터가 개선하는 건 "읽기"가 아니라 "바꾸기"인데, 모듈 2개(notices + 부활 예정 schedule)에 이만한 추상화가 과할 수 있다.

**축소 대안 (검토 후 기각)**: 모듈 진입점에서 `get_db()`만 걷어내고 컬렉션을 인자로 받게 하는 소수술 — 새 모듈의 DB 상속 문제는 풀린다. 기각 사유: OSS 목표(무인프라 실행)를 못 채운다. 컬렉션 주입만으로는 Mongo 타입이 여전히 시그니처에 남고, 증분 결정 로직이 저장소에 묶인 채다.

**조건부 수용**: 오픈소스 + 성장 전제(사용자 확정) 하에 채택하되, 조건이 결정 ⑨다 — 0.x로 공개하고 **1.0은 schedule이 두 번째 소비자로 실증한 뒤에만**. "두 번째 소비자가 생기기 전의 추상화는 추측"이라는 프레임워크 설계 경험칙을 게이트로 만든 것.

## 재검토 조건

- **모듈이 3개를 넘고** 서로 다른 저장소 백엔드를 요구하면 → `core.dedup`에 기본 해시 비교 술어를 둘지 재검토 (지금은 YAGNI: `has_changed`의 U+FFFD 절단 방어는 SKKU 목록 페이지 고유 특성)
- **외부 기여자가 자체 strategy를 들고 오면** → entry point 발견(`skkuverse_crawler.strategies` 그룹)을 추가 도입. 지금은 번들 고정, 추가는 파괴적이지 않은 변경
- **plugins/가 5개를 넘거나** 플러그인 간 하드 엣지가 2개 이상 생기면 → 다중 배포물(⑤ 후보 ①) 재개봉
- **`Stage`가 서비스 의존 단계를 3개 이상 갖게 되면** → 단계별 재시도·부분 실패 정책이 필요해지므로 파이프라인 계약 재설계
- **골든 테스트가 FakeCollection 버그로 거짓 통과한 사례가 1회라도 나오면** → 적합성 테스트 범위를 연산자 단위에서 시나리오 전량으로 확대 ([core-plugin-plan.md](../core-plugin-plan.md) §PR 0)
- *(v2)* **결과 계층에 이벤트 추가가 필요해지면** → 그 자체가 major 버전 신호. 진행 계층이 ~10종을 넘으면 2계층 구분 자체를 재평가 (§⑧)
- *(v2)* **1.0 태깅** → `schedule` 모듈이 프레임워크 위에 실제로 올라가 두 번째 소비자 검증을 통과한 뒤에만 (§⑬)
- *(v2)* **flush 소스 내 격리** (부분 실패 시 소스 계속 + `ItemFailed` 집계) → 1.0 전 재검토. 채택 시 골든 갱신 필요 (§⑪)
