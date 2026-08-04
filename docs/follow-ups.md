# Follow-ups — 열려 있는 작업 목록

adr-006 core/plugin 로드맵(PR 0~9)이 끝난 시점(2026-08-02)에 **알면서 남긴** 것들.
각 항목은 왜 지금 안 했는지와 제안 해법을 함께 적는다 — 이유 없는 TODO는 다음 사람이 지울지 고칠지 판단할 수 없다.

출처: PR 9 리뷰 라운드(코드 리뷰 + CI 감사), `core-plugin-plan.md` §범위 밖, `adr-006` §재검토 조건.

> 우선순위는 **사용자에게 도달하는 영향** 기준. P1은 지금 프로덕션에서 틀린 것, P2는 틀릴 수 있는 것, P3는 설계 부채.

---

> **배포 완료 및 검증됨 (2026-08-04).** 아래 P1·P2·8-b는 전부 프로덕션에 반영되고 실측으로 확인됐다. 결과는 §검증 결과 참조.

## ~~P1 — 지금 프로덕션에서 틀린 것~~ (2026-08-03 해결, 2026-08-04 검증)

두 건 모두 `fix/tier2-content-divergence`에서 수정. 아래는 무엇이 실제로 발견됐는지의 기록 — 둘 다 문서에 적었던 것보다 컸다.

### ~~1. `update_checker`가 `cleanMarkdown`을 갱신하지 않는다~~ ✅

**문서가 증상만 적고 있었다.** 코드를 열어 보니 네 갈래였고, 네 번째가 나머지 셋을 영구화하고 있었다.

| # | 필드 | 크롤 경로 | 수정 전 tier-2 |
|---|------|----------|---------------|
| 1 | `cleanMarkdown` | `html_to_markdown(cleaned)` | **없음** — 앱 1순위 렌더 소스라 수정된 공지가 옛 본문으로 보임 |
| 2 | `contentText` | `_text_from_clean_html(cleaned)` | `detail.contentText` — 2026-04에 넣은 블록 개행 보존이 사라짐 |
| 3 | 5MB 가드 | 초과 시 `cleanHtml`/`content` = None | **없음** — 16MB 문서 한도를 세 필드가 공유 |
| 4 | **이미지 측정** | `VerifyImages` → `InjectImageDimensions` | **없음** ← **근본 원인** |

**④가 왜 근본인가.** 크롤은 `<img>`마다 HTTP Range로 앞 32KB를 받아 크기를 재고 `width`/`height`를 주입한 뒤, **그 HTML에서** 해시를 뜨고 마크다운을 만든다(앱이 파싱하는 `{WxH}` 힌트). tier-2는 측정을 안 하므로 **같은 본문에서 다른 해시가 나온다.** 두 주체가 서로를 "변경됨"으로 판정하고 영원히 덮어쓴다.

프로덕션 실측 (2026-08-03):

```
articleNo 137297 (skku-main):  editCount 30, distinct 해시 2개
  06-13 06:00  tier1  72bdec → e4463d
  06-13 11:10  tier2  e4463d → 72bdec
  06-15 01:00  tier1  72bdec → e4463d      ... 30회 왕복
```

`cleanMarkdown`에 `{WxH}`가 있는데 `cleanHtml`엔 `width=`가 없는 문서 **2,115건** — tier-2가 HTML을 마지막에 썼다는 지문이다. 14일 창을 벗어나면 멈추므로 공지당 약 28회로 유계.

**해법**: `stages.derive_content_fields()`가 `DEFAULT_PIPELINE`을 **실제로 돌린다**. 손으로 만든 사본은 파이프라인과 같을 수 없으므로, 유일한 재발 방지는 같은 파이프라인을 쓰는 것뿐이다. tier-2 해시 == 크롤 해시가 되어 왕복이 영구 종료된다.

**비용**: 이미지 프로브. 14일 창 735건 중 274건이 이미지 보유(총 305개), 하루 3회 → 일 약 915 Range 요청 증가. 이미지 없는 461건은 `verify_notice_images`가 즉시 반환해 비용 0. 크롤 경로는 이미 신규 공지마다 같은 비용을 낸다.

#### ⚠️ 배포 직후 1~2회는 경보가 자기 자신을 향해 울린다 — **예측대로 일어났고 예측대로 멈췄다**

수정된 코드는 기존 문서들을 **처음으로 올바르게** 재측정하므로, 저장된(잘못된) 해시와 다르다. 즉 첫 tier-2 실행들이 정상적으로 `content_changed`를 대량 기록하고, 이 브랜치가 지키려는 그 경보가 함께 울린다.

| | 예측 (14일 창 773건 기준) | **실측** |
|---|---|---|
| `content_changed` | 231건 | **28건** |
| `high_change_rate` WARNING | 47개 소스 | **3개** |
| `likely_determinism_bug` ERROR | 16개 소스 | **3개** |

예측보다 훨씬 작았던 이유는 **복구(8-b)를 2시간 먼저 돌려** 2,628건의 해시를 미리 맞춰뒀기 때문이다. update-check가 마주할 불일치가 그만큼 줄었다.

`likely_determinism_bug` 3건은 전부 `checked: 1, changed: 1` — 14일 창에 공지가 한 건뿐인 소형 학과다. **비율 기반 경보가 표본 1에서 무의미해지는 구조적 한계**이지 결정론 버그가 아니다. (재검토 조건: 표본이 작을 때 경보를 억제할지 — 현재는 소음 수준이 낮아 미착수)

**이 예측을 미리 적어둔 것이 중요했다.** 없었다면 배포 당일 밤 ERROR 3건을 보고 롤백을 고민했을 것이다.

#### 골든 1건이 바뀐다

`std_null_backfill`의 `contentText` 한 필드. 백필 경로가 strategy 텍스트 대신 정제 HTML에서 추출하게 되면서 블록 개행이 복원된 것 — 리팩터의 부작용이 아니라 수정의 증거다. `cleanHtml`·`cleanMarkdown`·`contentHash`는 불변(픽스처에 이미지 없음). 나머지 7건은 바이트 동일.

**기각한 대안**: `derive_content_fields`를 `normalizer.py`에 두고 `build_notice`의 인라인 분기를 재현하는 안. 첫 시도가 이것이었고 **리뷰에서 잡혔다** — 인라인 분기는 docstring 스스로 "픽스처·품질 테스트용"이라 적어둔 경로이고 파이프라인이 아니다. 그래서 정의가 셋이 되고, 프로덕션이 그중 틀린 것을 가리켰다. `normalizer.py`는 원복했고 인라인↔파이프라인 동치는 기존 parity 테스트가 계속 지킨다.

### ~~2. `run_events`가 런 종료 시 `flush`하지 않는다~~ ✅

`_crawl_department`의 `aclosing` 블록 종료 직후 `await ports.sink.flush()`. `cli.py`의 수동 우회와 가이드의 ⚠️도 함께 제거 — 근본이 고쳐졌는데 우회가 남으면 그게 거짓말이 된다.

**문서의 예측이 틀렸다**: "빈 flush가 1회 늘어 골든 op 순서가 바뀐다"고 적었는데, `MongoSink.flush()`는 버퍼가 비면 `if not items: return`이라 컬렉션 연산을 일으키지 않는다. **이 flush 변경에 한해 골든 8건 바이트 동일** — 버그가 있던 경로에서만 동작을 바꾼다. (브랜치 전체로는 골든 1건이 바뀐다 — §1의 백필 통합 때문이며 거기 기록.)

---

## 검증 결과 (2026-08-04 실측)

배포 전 `content_changed`는 **0과 30을 왕복**했다 — 본문이 바뀌어서가 아니라 크롤과 tier-2가 서로의 해시를 "변경됨"으로 오판해서다.

```
update-check                       경보
2026-08-03 11:12  changed=28   6건   ← 1회성 정산
2026-08-03 23:12  changed=0    0건
2026-08-04 05:12  changed=2    0건   ← 실제로 수정된 공지 2건
```

`content_vanished`는 3회 연속 0 (새 가드 오탐 없음). `errors: 13`은 배포 전 11과 동급 — 도달 불가 소스의 상시 실패.

**크롤 회귀 없음:**

```
              depts   ins   upd   skip     err
배포 전        140    1~8  57~61  ≈29,806   0
배포 후        140    0~9  57~63  ≈30,061   0
```

**복구 결과 (8-b):**

```
적용            2,628건 / 49초
멱등 검증       재실행 repaired: 0, already_consistent: 2,755
손상 지문       2,126 → 0
이미지 차원 보유율  29% → 92%
```

가장 많이 고쳐진 필드는 `cleanMarkdown`(682)이 아니라 **`contentText`(2,306)**였다 — tier-2가 이미지 유무와 무관하게 모든 문서의 텍스트를 strategy 것으로 덮어써, 2026-04에 넣은 블록 개행 보존이 되돌려져 있었다.

---

## P2 — 틀릴 수 있는 것

### 3. flush 실패 시 소스 간 오염 (adr-006 §⑪ 1.0 전 재검토 항목)

**증상**: `MongoSink`의 touch 버퍼가 run 레벨이고 sink 인스턴스는 소스 간 공유된다(`Semaphore(5)`). 소스 A의 `flush`가 B가 mid-page에 버퍼한 touch를 함께 배출하므로, **A의 flush 실패가 B의 쓰기를 잃으면서 B는 성공으로 보고된다.** 데이터 정합성은 안전(op마다 `articleNo`+`sourceId` 필터, unordered) — 깨지는 건 실패 **귀속**이다.

**왜 지금 안 했나**: PR 5에서 페이지-로컬 → run-레벨 버퍼로 바뀐 의도된 델타이고, 골든에 비가시(전부 단일 소스)라 리팩터 중엔 안전하게 미룰 수 있었다.

**제안**: sink 인스턴스를 소스당 하나로. `run_crawl`이 `Ports` 번들을 소스마다 만들거나, `Sink`에 `for_source(spec) -> Sink` 팩토리 훅을 추가. 후자가 계약 확장이라 **1.0 전에 결정해야 한다**(추가는 breaking).
**대안(싼 쪽)**: 버퍼를 `dict[source_id, list]`로 쪼개고 `flush`가 호출자 소스만 배출 — 계약 무변경. 다만 `flush(source_id)` 시그니처가 필요해져 결국 계약을 건드린다.

### ~~4-b. 크롤과 tier-2가 이미지 프로브에 다른 Referer를 넘긴다~~ ✅ (2026-08-03)

emit 경로는 `f"{baseUrl}{detailPath}"`로 이어 붙이고 `build_notice`는 `urljoin`을 썼다. `detailPath`가 형제 파일명인 소스(`medicine`) 하나에서 `…/community_notice.aspcommunity_notice_w.asp?…`라는 깨진 URL이 나갔다. 같은 호스트라 hotlink 검사는 통과했지만, **해시를 결정하는 입력이 두 주체 간에 달랐다** — 이 브랜치의 전제와 정면 충돌. `normalizer.source_url_for()`로 통합.

### ~~4. `run_crawl`의 조기 return이 `fetcher.close()`를 건너뛴다~~ ✅ (2026-08-03)

본문을 `_run_crawl`로 분리하고 `run_crawl`이 `try/finally`로 감싸 close를 단일 지점에. 성공 경로 말미의 close도 흡수 — 모든 이탈 경로(조기 return, raise 포함)가 같은 곳을 지난다.

### 5-b. tier-2만 저장된 차원을 승계할 수 있다 — 비대칭 잔여분 *(신규, 2026-08-03)*

**증상**: 프로브가 일시 실패했을 때 tier-2는 저장된 `cleanHtml`에서 차원을 읽어 복원하지만, **크롤은 읽을 저장본이 없다**(신규 항목이거나 재크롤 중). 그래서 재크롤 중 프로브가 실패하면 차원 없는 해시가 저장되고, 다음 tier-2가 정상 프로브로 이를 "변경됨"으로 기록한다 — 1회성 `editCount` 증가.

**왜 핑퐁이 아닌가**: 크롤은 제목·날짜가 바뀔 때만 재수집하고, tier-2는 크롤이 마지막에 쓴 것에서 다시 시드하므로 **수렴한다.** 왕복이 아니라 잔여분이다.

**왜 지금 안 고쳤나**: 크롤 쪽도 저장본을 읽으려면 emit 경로가 SeenIndex를 넘어 문서 본문까지 조회해야 한다 — 증분 크롤의 조회 비용 구조를 바꾸는 일이고, 얻는 것(드문 1회성 오탐 제거)에 비해 크다.

**재개봉 조건**: `editHistory`에 tier2 단독 항목이 반복적으로 쌓이는 문서가 관측되면.

### 5-c. tier-2는 `attachments`를 갱신하지 않는다 *(기존, 기록만)*

`fields.as_set()`은 5개 콘텐츠 필드뿐이다. 크롤과 백필은 `attachments`를 쓰지만 tier-2는 안 쓴다 — 공지가 첨부만 교체되면 제목·날짜가 바뀌어 재크롤될 때까지 낡은 URL이 남는다. 해시와 무관하고 이 브랜치 이전부터 그랬으므로 범위 밖으로 뒀다. 다만 `TestTier2StoresTheSameFieldsAsACrawl`이라는 이름은 **콘텐츠 5필드에 한한 주장**이다.

### 5-d. tier-2에는 `pipeline` 파라미터가 없다 *(잠재)*

`run_crawl(pipeline=)`은 emit·백필 양쪽에 전달되지만 tier-2는 `DEFAULT_PIPELINE`을 하드코딩한다. `derive_content_fields` docstring이 `DEFAULT_PIPELINE.without("verify-images")`를 탈출구로 안내하는데, **크롤 쪽에서 그걸 쓰면 이 브랜치가 없앤 해시 불일치가 정확히 되살아난다.** 현재 커스텀 파이프라인을 넘기는 프로덕션 호출자는 없어 잠재 상태.

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

### ~~8-b. tier-2가 손상시킨 문서 백필~~ ✅ (2026-08-04 실행 완료)

**문서가 틀렸다.** "재크롤이 필요하다(로컬 재계산 불가)"라고 적었으나 **측정값은 이미 DB 안에 있었다** — tier-2는 `cleanHtml`만 덮어썼고 `cleanMarkdown`은 건드리지 않아, 낡은 마크다운이 `{WxH}` 힌트를 그대로 갖고 있었다.

**해법**: `repair-dimensions` 커맨드. 저장된 마크다운에서 차원을 읽어 `cleanHtml`에 재주입한 뒤 **파이프라인의 뒷부분만** 다시 돌린다 —

```
DEFAULT_PIPELINE.without("normalize-urls", "clean-html", "verify-images")
  = InjectImageDimensions → SizeGuard → ExtractText → ToMarkdown → ContentHash
```

앞 세 스테이지만 raw HTML을 필요로 한다. 저장된 `content`에서 `cleanHtml`을 다시 만드는 것은 **금지** — 이미 정규화된 HTML을 `clean_html`에 다시 먹이면 모든 공지 본문이 조용히 바뀐다(adr-006 §④).

**실행 결과 (2026-08-04)**: 2,628건 / 49초. 재실행 `repaired: 0` (멱등 실증). 손상 지문 2,126 → **0**, 이미지 차원 보유율 29% → **92%**.

**리뷰가 잡은 것**: 초안 정규식 `[^\]]*`가 이스케이프된 대괄호를 넘지 못해 `\[학사팀\]` 형태 알트 텍스트의 힌트를 못 읽었다. **못 읽은 힌트는 재주입도 못 하므로 마크다운 재생성에서 영구 소실** — 복구 도구가 복구 대상을 파괴하는 형태였고, 프로덕션 49건이 해당했다.

**커맨드는 남겨둔다** — 일회성이지만 tier-2가 다시 어긋나면 같은 도구가 필요하고, 멱등이라 상시 존재해도 해롭지 않다. 삭제 조건: `schedule` 모듈 탑재로 1.0을 태깅할 때 함께 정리.

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
| ~~13~~ ✅ | **`py/examples/*.py` 글롭이 무필터** | 해결 (2026-08-03) — `_` 접두 + `conftest.py` 스킵 |
| 14 | **월클럭 +20~30초.** `core-only`가 19초 → 약 3배. 1분 미만이라 현재는 무해 | `DEFAULT_MAX_PAGES=1`이 상한을 묶고 있으므로 추가 조치 불필요 |

---

## 하지 않기로 한 것 (재개봉 조건 포함)

`adr-006` §재검토 조건에 정식 기록됨. 요약:

- **다중 PyPI 배포물 분리** — extras가 의존성 격리를 제공하므로 불필요. **재개봉 조건**: `modules/` 트리 없이 `plugins/mongo`만 쓰려는 소비자가 나타날 때
- **`pluggy`** — 확장점 4개에 정당화 안 됨
- **Pydantic** — 현행 dataclass 유지
- **퍼블릭 코어 레포 분리** — 단일 레포 유지
- **기존 한국어 설계 문서 영역화** — adr·plan은 의사결정 기록이라 번역이 손실적. 신규 공개 문서(README·sink 가이드)만 영어
