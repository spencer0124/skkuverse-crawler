# Follow-ups — 열려 있는 작업 목록

adr-006 core/plugin 로드맵(PR 0~9)이 끝난 시점(2026-08-02)에 **알면서 남긴** 것들.
각 항목은 왜 지금 안 했는지와 제안 해법을 함께 적는다 — 이유 없는 TODO는 다음 사람이 지울지 고칠지 판단할 수 없다.

출처: PR 9 리뷰 라운드(코드 리뷰 + CI 감사), `core-plugin-plan.md` §범위 밖, `adr-006` §재검토 조건.

> 우선순위는 **사용자에게 도달하는 영향** 기준. P1은 지금 프로덕션에서 틀린 것, P2는 틀릴 수 있는 것, P3는 설계 부채.

---

## ~~P1 — 지금 프로덕션에서 틀린 것~~ (2026-08-03 해결)

두 건 모두 `fix/tier2-content-divergence`에서 수정. 아래는 무엇이 실제로 발견됐는지의 기록 — 둘 다 문서에 적었던 것보다 컸다.

### ~~1. `update_checker`가 `cleanMarkdown`을 갱신하지 않는다~~ ✅

**실제로는 세 갈래였다.** `cleanMarkdown` 누락은 셋 중 하나였고 나머지 둘도 전부 조용한 부패였다:

| 필드 | 크롤 경로 | 수정 전 tier-2 |
|------|----------|---------------|
| `cleanMarkdown` | `html_to_markdown(cleaned)` | **없음** — 앱 1순위 렌더 소스라 수정된 공지가 옛 본문으로 보임 |
| `contentText` | `_text_from_clean_html(cleaned)` | `detail.contentText` — 2026-04에 넣은 **블록 개행 보존이 사라짐** |
| 5MB 가드 | 초과 시 `cleanHtml`/`content` = None | **없음** — 16MB 문서 한도를 `content`+`cleanHtml`+`contentText`가 공유하므로 큰 공지 수정 시 업데이트 실패 가능 |

**해법은 제안 2번(근본 수정)을 택했다.** `normalizer.derive_content_fields()` + `ContentFields` 추출 — 다섯 필드가 무엇인지의 **단일 정의**이고, 크롤 경로의 인라인 분기와 tier-2가 둘 다 이걸 부른다. `ContentFields`의 필드명이 snake_case가 아니라 저장 필드명(camelCase)인 것은 의도: 양쪽이 이걸 `$set`으로 바꾸므로, 손으로 쓴 매핑이 두 벌 생기면 그게 바로 이 타입이 없애려는 그 드리프트다.

### ~~2. `run_events`가 런 종료 시 `flush`하지 않는다~~ ✅

`_crawl_department`의 `aclosing` 블록 종료 직후 `await ports.sink.flush()`. `cli.py`의 수동 우회와 가이드의 ⚠️도 함께 제거 — 근본이 고쳐졌는데 우회가 남으면 그게 거짓말이 된다.

**문서의 예측이 틀렸다**: "빈 flush가 1회 늘어 골든 op 순서가 바뀐다"고 적었는데, `MongoSink.flush()`는 버퍼가 비면 `if not items: return`이라 컬렉션 연산을 일으키지 않는다. **골든 8건 바이트 동일 유지** — 이 수정은 버그가 있던 경로에서만 동작을 바꾼다.

---

## P2 — 틀릴 수 있는 것

### 3. flush 실패 시 소스 간 오염 (adr-006 §⑪ 1.0 전 재검토 항목)

**증상**: `MongoSink`의 touch 버퍼가 run 레벨이고 sink 인스턴스는 소스 간 공유된다(`Semaphore(5)`). 소스 A의 `flush`가 B가 mid-page에 버퍼한 touch를 함께 배출하므로, **A의 flush 실패가 B의 쓰기를 잃으면서 B는 성공으로 보고된다.** 데이터 정합성은 안전(op마다 `articleNo`+`sourceId` 필터, unordered) — 깨지는 건 실패 **귀속**이다.

**왜 지금 안 했나**: PR 5에서 페이지-로컬 → run-레벨 버퍼로 바뀐 의도된 델타이고, 골든에 비가시(전부 단일 소스)라 리팩터 중엔 안전하게 미룰 수 있었다.

**제안**: sink 인스턴스를 소스당 하나로. `run_crawl`이 `Ports` 번들을 소스마다 만들거나, `Sink`에 `for_source(spec) -> Sink` 팩토리 훅을 추가. 후자가 계약 확장이라 **1.0 전에 결정해야 한다**(추가는 breaking).
**대안(싼 쪽)**: 버퍼를 `dict[source_id, list]`로 쪼개고 `flush`가 호출자 소스만 배출 — 계약 무변경. 다만 `flush(source_id)` 시그니처가 필요해져 결국 계약을 건드린다.

### ~~4. `run_crawl`의 조기 return이 `fetcher.close()`를 건너뛴다~~ ✅ (2026-08-03)

본문을 `_run_crawl`로 분리하고 `run_crawl`이 `try/finally`로 감싸 close를 단일 지점에. 성공 경로 말미의 close도 흡수 — 모든 이탈 경로(조기 return, raise 포함)가 같은 곳을 지난다.

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

### 8-b. tier-2 부패 문서 백필 *(신규, 2026-08-03)*

P1-1은 **앞으로**를 고쳤다. 이미 tier-2로 수정된 문서의 `cleanMarkdown`·`contentText`는 여전히 낡았다.

**왜 어려운가**: `contentHash`는 최신인데 `cleanMarkdown`이 옛 해시 기준인 문서를 특정할 방법이 없다 — 마크다운에 해시가 없기 때문이다. 부패 여부를 질의로 판별할 수 없다.

**제안**: `editHistory`에 `source: "tier2"` 항목이 있는 문서를 전부 골라 `cleanHtml`에서 `cleanMarkdown`·`contentText`를 재생성. `cleanHtml`은 tier-2가 정확히 써 왔으므로 재크롤 없이 로컬 재계산으로 충분하다.
**규모 확인 먼저**: `db.notices.count({"editHistory.source": "tier2"})`.

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
| ~~12~~ ✅ | **`quickstart.py` 실패 메시지가 오해를 부른다** | 해결 (2026-08-03) — `code broken, or skku.edu unreachable from CI?`로 확장 |
| ~~13~~ ✅ | **`py/examples/*.py` 글롭이 무필터** | 해결 (2026-08-03) — `_` 접두 파일 스킵 |
| 14 | **월클럭 +20~30초.** `core-only`가 19초 → 약 3배. 1분 미만이라 현재는 무해 | `DEFAULT_MAX_PAGES=1`이 상한을 묶고 있으므로 추가 조치 불필요 |

---

## 하지 않기로 한 것 (재개봉 조건 포함)

`adr-006` §재검토 조건에 정식 기록됨. 요약:

- **다중 PyPI 배포물 분리** — extras가 의존성 격리를 제공하므로 불필요. **재개봉 조건**: `modules/` 트리 없이 `plugins/mongo`만 쓰려는 소비자가 나타날 때
- **`pluggy`** — 확장점 4개에 정당화 안 됨
- **Pydantic** — 현행 dataclass 유지
- **퍼블릭 코어 레포 분리** — 단일 레포 유지
- **기존 한국어 설계 문서 영역화** — adr·plan은 의사결정 기록이라 번역이 손실적. 신규 공개 문서(README·sink 가이드)만 영어
