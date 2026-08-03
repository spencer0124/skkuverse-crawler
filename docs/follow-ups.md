# Follow-ups — 열려 있는 작업 목록

adr-006 core/plugin 로드맵(PR 0~9)이 끝난 시점(2026-08-02)에 **알면서 남긴** 것들.
각 항목은 왜 지금 안 했는지와 제안 해법을 함께 적는다 — 이유 없는 TODO는 다음 사람이 지울지 고칠지 판단할 수 없다.

출처: PR 9 리뷰 라운드(코드 리뷰 + CI 감사), `core-plugin-plan.md` §범위 밖, `adr-006` §재검토 조건.

> 우선순위는 **사용자에게 도달하는 영향** 기준. P1은 지금 프로덕션에서 틀린 것, P2는 틀릴 수 있는 것, P3는 설계 부채.

---

## ~~P1 — 지금 프로덕션에서 틀린 것~~ (2026-08-03 해결)

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

**기각한 대안**: `derive_content_fields`를 `normalizer.py`에 두고 `build_notice`의 인라인 분기를 재현하는 안. 첫 시도가 이것이었고 **리뷰에서 잡혔다** — 인라인 분기는 docstring 스스로 "픽스처·품질 테스트용"이라 적어둔 경로이고 파이프라인이 아니다. 그래서 정의가 셋이 되고, 프로덕션이 그중 틀린 것을 가리켰다. `normalizer.py`는 원복했고 인라인↔파이프라인 동치는 기존 parity 테스트가 계속 지킨다.

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

### ~~4-b. 크롤과 tier-2가 이미지 프로브에 다른 Referer를 넘긴다~~ ✅ (2026-08-03)

emit 경로는 `f"{baseUrl}{detailPath}"`로 이어 붙이고 `build_notice`는 `urljoin`을 썼다. `detailPath`가 형제 파일명인 소스(`medicine`) 하나에서 `…/community_notice.aspcommunity_notice_w.asp?…`라는 깨진 URL이 나갔다. 같은 호스트라 hotlink 검사는 통과했지만, **해시를 결정하는 입력이 두 주체 간에 달랐다** — 이 브랜치의 전제와 정면 충돌. `normalizer.source_url_for()`로 통합.

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

### 8-b. tier-2가 손상시킨 문서 백필 *(신규, 2026-08-03)* — **P1 대기**

P1-1은 **앞으로**를 고쳤다. 이미 손상된 문서는 그대로다.

**규모** (2026-08-03 실측): `cleanMarkdown`에 `{WxH}`가 있는데 `cleanHtml`엔 `width=`가 없는 문서 **2,115건**. 이들은 `cleanHtml`에서 이미지 크기를 잃었고, `contentText`도 tier-2가 쓴 구포맷(개행 뭉개짐)일 가능성이 높다.

**왜 질의로 특정이 어려운가**: `cleanMarkdown`이 낡았는지는 마크다운만 보고 알 수 없다(해시가 없음). 다만 위 조합(`md`에 힌트 O + `html`에 width X)이 **tier-2가 마지막에 썼다는 신뢰할 만한 지문**이라 이걸 선별 기준으로 쓸 수 있다.

**제안**:
1. 규모 재확인 — 위 조합 + `editHistory.source == "tier2"` 보유 문서 수.
2. **재크롤이 필요하다** (로컬 재계산 불가): 이미지 크기는 원본 이미지를 다시 받아야 나온다. `update-check --days N`을 넓은 창으로 돌리면 상당수가 자연 복구된다 — 별도 스크립트 불필요.
3. ⚠️ **다만 전부는 아니다.** 복구는 `old_hash != new_hash`일 때만 쓰기가 일어나는 부수 효과다. 이미지가 **더 이상 측정되지 않는** 문서(첨부 삭제, 죽은 CDN, 파싱 불가 포맷)는 수정된 코드도 tier-2가 이미 저장한 것과 같은 차원 없는 해시를 재현하므로 **쓰기가 일어나지 않고 낡은 `cleanMarkdown`이 살아남는다.** 실측 기준선: 이미지 보유 문서 중 약 17%가 측정 불가 상태 → 2,115건 중 대략 300~400건.
4. 그 잔여분은 해시 비교를 우회하는 강제 재작성이 필요하다 — 별도 1회성 스크립트, 또는 대상 문서의 `contentHash`를 `null`로 만들어 backfill 분기를 타게 하는 방법.
5. 창을 넓히면 프로브 비용이 그만큼 늘어나므로 1회성으로, 트래픽 적은 시간대에.

**검증**: 실행 후 위 조합 문서 수가 0으로 수렴하는지, `content_changed`가 1회성 급증 후 정상화되는지.

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
