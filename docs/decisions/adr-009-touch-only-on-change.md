# ADR-009: 무변경 공지는 쓰지 않는다 — `crawledAt`은 "마지막 관측"이 아니라 "마지막 변경"

- **상태**: 채택됨 (2026-09-13) · **개정됨 (2026-09-13 — per-document jitter, 아래 참조)**
- **관련**: [skkuverse#52](https://github.com/spencer0124/skkuverse/issues/52),
  [adr-006](adr-006-core-plugin-split.md) (위험 ② — `bulk_touch_notices`가 조용히 증발하는 것),
  서버 [ADR 0007](https://github.com/spencer0124/skkuverse-server/blob/main/docs/decisions/0007-notice-ordering-key.md) ·
  [ADR 0008](https://github.com/spencer0124/skkuverse-server/blob/main/docs/decisions/0008-dispatch-age-gate-on-publication-date.md)

## 맥락

`notices`는 `*/30 * * * *`로 돌고, 매 틱마다 모든 소스의 page 0을 다시 읽는다. 바뀐 게
없는 항목은 `ItemUnchanged`로 흘러 `MongoSink`가 버퍼링하고, flush에서 한 번의
`bulk_write`로 **전부** 다시 쓴다 — 페이로드는 `{"views": n, "crawledAt": now}` 뿐이다.

2026-09-06 프로덕션 실측:

| | |
|---|---|
| 한 틱의 쓰기 | 1,264건 / 115개 소스 (13:30–13:31) |
| 초당 피크 | 93건/s |
| 컬렉션 크기 | ~8,800 docs |
| 같은 24h에 `editHistory`가 늘어난 문서 | ~209건/일 (틱당 ~4건) |

**쓰기의 약 99.7%가 독자에게 보이는 것을 아무것도 바꾸지 않는다.** 컬렉션의 14.6%를 30분마다
다시 쓰고 나머지 29분은 논다.

문제는 비용만이 아니었다. `crawledAt`은 서버의 리스트 정렬 키이기도 했고, `date`가
day-granular 문자열이라 같은 날짜 안에서는 `crawledAt`이 실제 순서를 정한다. 매 틱이
page-0 부분집합만 `now`로 올리니 **같은 날짜 공지 두 건의 상대 순서가 틱마다 뒤집혔다** —
커서가 행을 건너뛰거나 두 번 주는 전형적인 조건. 2026-09-06 실측으로 39개
`(sourceId, date)` 그룹 / 247개 문서가 그 상태였다.

### 이미 우리 코드가 두 번 반대표를 던졌다

- **tier-2 `update_checker.py`는 변경이 있을 때만 `crawledAt`을 쓴다** (`:267`, `:290`).
  무변경 케이스는 아예 건너뛴다. tier-1의 touch만 예외였다.
- **`plugins/health/probes.py`의 first-seen 카운트는 `crawledAt`을 일부러 피하고**
  ObjectId 임베드 타임스탬프를 쓴다. 주석이 그 이유로 touch를 지목한다 (`:65-68`).

## 결정

**`ItemUnchanged`의 `fields`가 비어 있으면 아무것도 쓰지 않는다.** `crawledAt`의 의미를
"마지막 관측"에서 **"마지막 변경"**으로 좁혀, tier-2가 이미 하던 것과 일치시킨다.

세 지점:

1. **`SeenRecord`에 `views` 추가** (`core/ports.py`) + `MongoSeenIndex.lookup` projection에
   `views: 1` (`plugins/mongo/seen.py`). 이미 도는 `find`에 필드 하나를 얹는 것이라 추가
   왕복이 없다. `content_hash`와 같은 이유로 기본값은 `None`.
2. **`_emit_page`가 조회수가 실제로 움직였을 때만 페이로드를 싣는다**
   (`modules/notices/orchestrator.py`). 이벤트는 무조건 yield하므로 `runner.py`의
   `result.skipped` 집계는 그대로다.
3. **`MongoSink.accept`이 빈 `fields`를 버퍼링하지 않는다** (`plugins/mongo/sink.py`).
   여전히 `None`을 반환하므로 sink contract(`core/testing.py`)는 영향 없음.

### "바뀌었으면 쓴다"만으로는 부족했다 — 실측이 설계를 바꿨다

처음 구현은 `item.views != existing.views` 하나였다. **그것만으로는 거의 아무것도
줄지 않는다.** 조회수는 30분 안에 실제로 움직인다:

- **dev 셰도우 런**: `skku-main`을 **32초** 간격으로 두 번 크롤 → 무변경 31행 중
  **23행(74%)이 여전히 쓰였다.** 간격이 30분이면 더 늘지 줄지 않는다.
- **프로덕션 모델링** (오늘 touch된 1,455건, 문서별 조회율 `views / 문서나이`,
  틱당 1회 이상 조회될 확률 `1 - e^(-rate)`): **예상 809건/틱** — 44% 감소에 그친다.
  41%(601건)는 반 시간에 1회 이상 조회되어 사실상 매 틱 쓰인다.

`crawledAt`을 없앤 것만으로 쓰기 이유 둘 중 하나만 사라졌고, 남은 하나(`views`)는
**진짜로 변하는 필드**라서 "변했나?"라는 질문으로는 걸러지지 않는다.

그래서 `views_refresh_due()` (`modules/notices/policy.py`)가 실제 정책을 진다:

| 조건 | 역할 |
|---|---|
| 조회수 무변동 | 쓰지 않음 (기존 규칙) |
| 마지막 쓰기 후 6h 미만 **AND** 변동폭 < `max(50, 10%)` | 쓰지 않음 ← **비용을 줄이는 실제 레버** |
| 변동폭 ≥ `max(50, 10%)` | 즉시 씀 — 급상승 공지가 6h 동안 틀린 숫자를 보이지 않게 |
| 저장된 `views`가 없음 | 즉시 씀 (1회 backfill) |

같은 추정기로 이 규칙을 재계산: **예상 119건/틱** — 1,264건 대비 **약 92% 감소**.
이슈가 제시한 ~139건/틱 바닥보다도 낮다.

### 2026-09-13 개정 — 평평한 interval은 평균만 고치고 peak은 못 고친다

배포 직후 첫 틱(12:00Z) 실측: **139개 학과 / 32,757건 조회 / 쓰기 1건.** 숫자는 좋지만
**그건 정상 상태가 아니라 사이클의 골짜기였다.** 배포 직전 틱(11:30Z)이 모든 page-0 문서를
같은 2분 안에 써버렸기 때문에, 12:00에는 전부 interval 안쪽이었다.

문제는 그 다음이다. 같은 2분 안에 쓰인 문서들은 **같은 2분 안에 interval을 빠져나간다** —
6시간 뒤 ~1,455건이 한 틱에 몰린다. 즉 평평한 interval은 48회/일 잔물결을 **4회/일 같은
높이의 스파이크**로 바꿀 뿐이다. Atlas 티어가 과금하는 축은 peak ops/s이므로
([이슈 §5 option 3](https://github.com/spencer0124/skkuverse/issues/52)이 바로 그 논지였다)
이건 논쟁의 절반만 이긴 것이다.

**`VIEWS_REFRESH_JITTER_HOURS = 4`** — `articleNo % 4` 시간을 interval에 **더한다**.

- `articleNo` 기반이라 **저장 상태도 스키마 변경도 필요 없고**, 재시작·재크롤에도 같은
  문서는 항상 같은 슬롯에 떨어진다. 매 패스마다 슬롯이 바뀌면 문서가 계속 이른 슬롯으로
  미끄러져 interval 자체가 무력화된다.
- **가산만 한다** — 어떤 문서도 `VIEWS_REFRESH_MIN_INTERVAL_HOURS`보다 일찍 due가 되지
  않는다 (테스트가 50개 articleNo에 대해 명시).
- 200개 코호트 시뮬레이션: 6/7/8/9시간에 50/100/150/200건 누적 — 시간당 정확히 25%씩
  풀린다. 배포 후 **한 사이클이면 herd가 영구히 흩어진다.**

**앱은 조회수를 전체 자릿수로 렌더한다** (`formatViews`는 천 단위 구분자만 넣는다 —
"1.2k" 반올림이 아니다). 즉 이 staleness는 **눈에 보인다**. 감추는 게 아니라 상대
오차로 묶는 것이 위 두 임계값의 목적이다: 최대 6시간, 또는 10%(최소 50) 이내.

### 조회수 비교를 `has_changed()`에 넣지 않은 이유

**`has_changed()`는 "상세 페이지를 다시 가져올까"를 결정한다.** 거기에 조회수를 넣으면
카운터가 1 오를 때마다 전체 detail 크롤이 돌아, 지금 없애려는 DB 쓰기보다 훨씬 비싼
네트워크 회귀가 된다. 비교는 `ItemUnchanged`를 만드는 자리에만 있어야 한다.

### `views` 기본값이 `0`이 아니라 `None`인 이유

`None`은 어떤 관측값과도 같지 않으므로, 필드가 없던 문서는 **한 번 쓰이고 backfill된다.**
부재를 `0`으로 읽으면 조회수를 노출하지 않는 소스의 문서가 영원히 `0`에 얼어붙는다.

## 선행 조건 — 서버가 먼저다

이 변경은 단독으로 배포하면 **푸시를 조용히 죽인다.**

서버의 FCM dispatch 게이트가 `crawledAt > now - 24h`였다. touch가 매 틱 `crawledAt`을
갱신하니, 그 술어는 실제로는 "아직 page 0에 있나?"를 물었고 — **요약이 늦게 붙는 공지를
자격 유지시켜 주는 유일한 장치**였다. 2026년 9월 삽입분 실측: n=313, 평균 지연 5.8h,
최대 71.9h, **24h 초과 28건 (8.9%)**. touch를 멈추면 그 28건은 창 밖으로 나가 영영 발송되지
않는다. 에러 경로도 없다 — sweep이 그 행을 고르지 않을 뿐이다.

**따라서 배포 순서는 서버 ADR 0007 → 0008 → 이 변경이다.** 0008이 게이트를 공지 자체의
게시일(`date`, Asia/Seoul, 14일)로 옮긴 뒤에만 이 커밋을 배포할 수 있다.

## 결과

- (+) 틱당 쓰기가 1,264건에서 "실제 변경분 + 조회수가 움직인 행"으로 떨어진다.
- (+) `crawledAt`이 tier-1·tier-2에서 같은 뜻을 갖는다. 지금까지는 두 경로가 같은 필드에
  다른 의미를 쓰고 있었다.
- (−) **조회수가 최대 6시간(또는 10%) 낡을 수 있고, 그게 화면에 보인다.** 앱이 전체
  자릿수로 렌더하기 때문. 이미 "마지막 크롤 시점" 값이었지 실시간이 아니었으므로 성격이
  바뀐 건 아니고 오차 한도가 30분에서 6시간으로 늘었다. 조회수는 의사결정에 쓰이지 않는
  soft signal이라 감수 가능하다고 판단.
- (−) 골든 스냅샷의 의미가 뒤집혔다. adr-006 위험 ②는 "touch가 조용히 사라진다"였는데,
  이제 위험은 **"touch가 조용히 돌아온다"**다. `test_std_three_rounds`가 그 방향으로
  재작성됐다 — 무변경 페이지는 `bulk_write`가 0이어야 하고, 동시에 `skipped == 4`여야 한다
  ("아무것도 안 썼다"와 "아무것도 못 봤다"는 구분 가능해야 한다).

## 재검토 조건

- 조회수 staleness가 제품 이슈로 올라올 때 — `VIEWS_REFRESH_MIN_INTERVAL_HOURS`를 낮추면
  선형으로 쓰기가 늘어난다 (6h → 3h면 틱당 ~119 → ~230). 세 상수 모두
  `modules/notices/constants.py`가 SSOT.
- interval을 바꿀 때 **jitter도 같이 보라.** 최대 staleness는 interval + jitter이고
  (지금은 6~10h), jitter가 interval보다 크게 남으면 분산은 좋아져도 staleness 상한이
  흐려진다.
- 소스 수가 크게 늘어 "실제로 움직이는 행"만으로도 틱당 쓰기가 다시 수백 건이 될 때.
