# Follow-ups — 열려 있는 작업 목록

adr-006 core/plugin 로드맵(PR 0~9)이 끝난 시점(2026-08-02)에 **알면서 남긴** 것들.
각 항목은 왜 지금 안 했는지와 제안 해법을 함께 적는다 — 이유 없는 TODO는 다음 사람이 지울지 고칠지 판단할 수 없다.

출처: PR 9 리뷰 라운드(코드 리뷰 + CI 감사), `core-plugin-plan.md` §범위 밖, `adr-006` §재검토 조건.

> 우선순위는 **사용자에게 도달하는 영향** 기준. P1은 지금 프로덕션에서 틀린 것, P2는 틀릴 수 있는 것, P3는 설계 부채.

---

## P1 — 지금 프로덕션에서 틀린 것

### 1. `update_checker`가 `cleanMarkdown`을 갱신하지 않는다 (실버그)

**증상**: Tier-2 변경 감지가 공지 본문 변경을 잡으면 `content`·`cleanHtml`·`contentHash`는 재작성하는데 **`cleanMarkdown`은 재계산하지 않는다.** 앱은 `cleanMarkdown`을 1순위 렌더 소스로 쓰므로(`docs/api-design-reference.md` §본문 필드 선택 가이드), **Tier-2로 수정된 공지는 앱에서 옛 본문이 보인다.** 무증상 데이터 부패라 사용자 신고로만 발견된다.

**왜 지금 안 했나**: 리팩터 전 기간 내내 제1 원칙이 "골든 바이트 동일"이었다. 이 수정은 저장 필드를 바꾸므로 골든을 갱신해야 하고, 그러면 "리팩터가 동작을 안 바꿨다"는 증명이 오염된다. 로드맵이 끝난 지금은 그 제약이 사라졌다.

**제안**:
1. `plugins/mongo/update_checker.py`의 `$set` 필드 목록에 `cleanMarkdown: html_to_markdown(cleaned)` 추가 — 크롤 경로(`normalizer.build_notice`)가 이미 하는 것과 동일한 호출.
2. 두 경로가 다시 갈라지지 않게, 필드 조립을 한 함수로 뽑아 양쪽이 부르게 할 것. **이게 근본 수정이고 1번은 증상 수정이다.**
3. 기존 부패 문서 백필: `contentHash`는 최신인데 `cleanMarkdown`이 옛 해시 기준인 문서를 찾을 방법이 없다(마크다운에 해시가 없음). 실용적 대안 — `editHistory`에 tier2 항목이 있는 문서 전량 재생성.

**검증**: `tests/plugins/mongo/test_update_checker.py`에 "본문 변경 시 cleanMarkdown이 새 내용을 반영한다" 테스트 추가. 골든 갱신은 이 PR에서 정당하다.

---

### 2. `run_events`가 런 종료 시 `flush`하지 않는다 — 서드파티 sink 데이터 유실

**증상**: `core/runner.py::run_events`는 `PageCompleted`에서만 `flush()`한다. 그런데
- null-content 백필이 `ContentRefreshed`(쓰기 동반 결과 계층)를 **페이지 루프 이전**에 방출하고,
- 페이지 0 fetch 실패 / 빈 페이지 0은 `PageCompleted` **없이** 루프를 빠져나간다.

따라서 배칭 sink의 버퍼에 남은 쓰기가 영영 안 나가는데, **러너는 `result.updated`를 올려 "썼다"고 보고한다**. 실측: `flushes: 0`, `updated: 1`.

**왜 지금 안 했나**: 러너 동작 변경 = 골든 갱신. PR 9은 문서 PR이고 크롤 경로 무변경이 증거였다.

**현재 완화**: `modules/notices/cli.py`가 `run_crawl` 이후 수동 `await sink.flush()`를 호출한다(주석에 이유 명시). **자체 코드는 안전하고, `run_crawl`을 직접 부르는 서드파티만 노출된다.** `docs/sink-authors-guide.md`에 ⚠️로 명시해 뒀다.

**제안**: `_crawl_department`의 `aclosing` 블록 종료 직후 `await ports.sink.flush()` 1줄. 멱등이어야 하는 `flush` 계약상 안전(빈 버퍼 = no-op, 적합성 스위트가 강제). 이후 cli.py의 수동 호출과 가이드의 ⚠️를 함께 제거.
**주의**: MongoSink에 마지막 페이지 이후 빈 `flush`가 1회 늘어 골든의 op 순서가 바뀐다 — 스냅샷 갱신이 이 변경의 정당한 산출물이다.

---

## P2 — 틀릴 수 있는 것

### 3. flush 실패 시 소스 간 오염 (adr-006 §⑪ 1.0 전 재검토 항목)

**증상**: `MongoSink`의 touch 버퍼가 run 레벨이고 sink 인스턴스는 소스 간 공유된다(`Semaphore(5)`). 소스 A의 `flush`가 B가 mid-page에 버퍼한 touch를 함께 배출하므로, **A의 flush 실패가 B의 쓰기를 잃으면서 B는 성공으로 보고된다.** 데이터 정합성은 안전(op마다 `articleNo`+`sourceId` 필터, unordered) — 깨지는 건 실패 **귀속**이다.

**왜 지금 안 했나**: PR 5에서 페이지-로컬 → run-레벨 버퍼로 바뀐 의도된 델타이고, 골든에 비가시(전부 단일 소스)라 리팩터 중엔 안전하게 미룰 수 있었다.

**제안**: sink 인스턴스를 소스당 하나로. `run_crawl`이 `Ports` 번들을 소스마다 만들거나, `Sink`에 `for_source(spec) -> Sink` 팩토리 훅을 추가. 후자가 계약 확장이라 **1.0 전에 결정해야 한다**(추가는 breaking).
**대안(싼 쪽)**: 버퍼를 `dict[source_id, list]`로 쪼개고 `flush`가 호출자 소스만 배출 — 계약 무변경. 다만 `flush(source_id)` 시그니처가 필요해져 결국 계약을 건드린다.

### 4. `run_crawl`의 조기 return이 `fetcher.close()`를 건너뛴다

**증상**: `orchestrator.py`의 `no_matching_departments` 분기가 `Fetcher` 생성 후 `close()` 없이 return. httpx 클라이언트 누수.

**왜 지금 안 했나**: PR 6에서 발견했으나 "몰래 고치지 않는다" 원칙(리팩터 커밋에 무관한 수정 금지)에 따라 별건 등록.

**제안**: `try/finally`로 `run_crawl` 본문 전체를 감싸 `await fetcher.close()`를 단일 지점에. 현재 성공 경로 끝의 `close()`도 흡수. 오탐 없음 — 이 분기는 필터가 아무것도 안 걸렀을 때만 도달.

### 5. `SeenIndex.lookup`이 비스트리밍 (adr-006 1.0 전 판단)

**증상**: Mongo 구현이 커서를 전부 dict로 물어온다. 페이지당 ~10건이라 현재 무해.

**왜 지금 안 했나**: 실측상 문제가 없고, 스트리밍 인터페이스로의 변경은 **breaking**이라 0.x 창이 닫히기 전에만 결정하면 된다.

**제안**: 1.0 태깅 직전에 판정. 배치 크기가 페이지당 100건을 넘는 소비자가 나타나면 그때가 트리거.

---

## P3 — 설계 부채 / 미완 정리

### 6. `shared/` 해체 미완

`core-plugin-architecture.md` §레이아웃의 목표 배치(`fetcher`→core, `html_*`→core, `db`→plugins/mongo, `logger`→core)가 미이행. 현재 `shared/`는 "아직 층에 배정되지 않은 것" 서랍이다.
**왜 안 했나**: 로드맵의 위험 예산을 orchestrator 해체에 썼고, `shared/`는 순수 이동이라 언제 해도 값이 같다.
**제안**: `git mv` + import 정정만 하는 단일 PR. `test_core_import_stays_stdlib_only`가 `fetcher`(httpx)·`html_cleaner`(bs4/nh3) 이동을 막으므로 **core로 옮기려면 그 테스트의 stdlib-only 계약부터 재론해야 한다** — 이게 이 이동의 진짜 결정 사항이고, 기계적 이동이 아니다.

### 7. `build_notice(content=None)` 이중 경로

파이프라인 경로와 인라인 경로가 공존하고 parity 테스트가 5개 콘텐츠 형태에서 동치를 강제 중.
**왜 안 했나**: 단일화는 의미 결정(빈 문자열 `""` vs `None` 처리가 두 경로에서 다름)이지 기계적 이동이 아니다.
**제안**: 백필 경로(`ContentRefreshed`)의 무가드 `""`와 emit 경로의 `if detail.content` 가드 중 어느 쪽이 옳은지 먼저 정하고, 그 다음 통합.

### 8. `schedule` 모듈 포팅 — **1.0의 게이트**

`feat/schedule-crawler` 8ad3e8e를 이 프레임워크 위로.
**왜 중요한가**: adr-006 §⑬이 1.0을 여기 걸었다. 소비자가 하나뿐인 추상화는 검증 안 된 추측이므로, `CrawlModule`·`Sink`·`CrawlMode`가 두 번째 모듈을 실제로 견디는지 봐야 한다. `test_the_version_is_still_0_x`가 이 게이트를 강제한다.
**제안**: 포팅하며 코어가 강요한 어색함을 전부 기록할 것 — 그 목록이 1.0 API의 마지막 수정 기회다.

### 9. PyPI 발행 워크플로 + `readme` 필드

README는 레포 루트, 빌드 루트는 `py/`. PEP 621이 `../README.md`를 거부하므로 `readme` 미설정 상태.
**제안**: 발행을 실제로 할 때 함께 결정 — (a) `py/README.md`를 두고 루트는 심볼릭/요약, (b) hatch `force-include`로 끌어오기, (c) 루트를 빌드 컨텍스트로. 발행 의사가 없으면 아무것도 안 하는 게 맞다.

### 10. 서드파티 strategy entry point 발견

현재 `STRATEGY_MAP`은 번들 고정.
**트리거**: 외부 기여자가 자체 strategy를 들고 올 때. 추가는 파괴적이지 않으므로 그때 해도 늦지 않다.

---

## CI — 결함 아님, 기록해 둘 리스크

PR 9의 Actions 감사 결과: **회귀 없음**(`deploy.yml`·`claude.yml` 무변경, `core-only` 잡에 스텝 1개 추가만, `uv lock --check` 통과). 아래는 나중에 물 수 있는 것들.

| # | 리스크 | 완화 |
|---|--------|------|
| 11 | **라이브 네트워크 의존 증폭.** `core-only` 잡은 이미 skku.edu를 실크롤했고(9초), 예제 2개가 더 붙어 PR당 `skku-main` 페이지 1을 3회 친다. skku.edu 장애·레이트리밋이 문서만 고친 PR을 빨갛게 만든다 | 실제로 플래키해지면 이 스텝에 `continue-on-error: true`, 또는 매 PR이 아니라 스케줄/경로 필터 트리거로 이동 |
| 12 | **`quickstart.py` 실패 메시지가 오해를 부른다.** `iter_source`가 fetch 예외를 삼키고 계속하므로, 일시적 네트워크 실패는 exit 0 + 빈 stdout → 스텝이 `quickstart.py printed nothing`이라고만 말한다. 코드 버그처럼 읽힌다 | 메시지를 `printed nothing (source unreachable?)`로 넓히기 |
| 13 | **`py/examples/*.py` 글롭이 무필터.** 공용 헬퍼·`__init__.py`·`conftest.py`를 넣으면 그것도 실행되고 `test -s`에서 실패 | `_` 접두 파일 스킵, 또는 헬퍼는 하위 디렉토리에 |
| 14 | **월클럭 +20~30초.** `core-only`가 19초 → 약 3배. 1분 미만이라 현재는 무해 | `DEFAULT_MAX_PAGES=1`이 상한을 묶고 있으므로 추가 조치 불필요 |

---

## 하지 않기로 한 것 (재개봉 조건 포함)

`adr-006` §재검토 조건에 정식 기록됨. 요약:

- **다중 PyPI 배포물 분리** — extras가 의존성 격리를 제공하므로 불필요. **재개봉 조건**: `modules/` 트리 없이 `plugins/mongo`만 쓰려는 소비자가 나타날 때
- **`pluggy`** — 확장점 4개에 정당화 안 됨
- **Pydantic** — 현행 dataclass 유지
- **퍼블릭 코어 레포 분리** — 단일 레포 유지
- **기존 한국어 설계 문서 영역화** — adr·plan은 의사결정 기록이라 번역이 손실적. 신규 공개 문서(README·sink 가이드)만 영어
