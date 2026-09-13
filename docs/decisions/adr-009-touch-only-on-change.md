# ADR-009: 무변경 공지는 쓰지 않는다 — `crawledAt`은 "마지막 관측"이 아니라 "마지막 변경"

- **상태**: 채택됨 (2026-09-13)
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
- (−) **조회수가 자체적으로는 최신이 아니다.** 목록에 조회수 변동이 잡히지 않는 소스라면
  `views`가 마지막 변경 시점에 머문다. 목록 페이지가 조회수를 주는 소스는 영향 없다.
- (−) 골든 스냅샷의 의미가 뒤집혔다. adr-006 위험 ②는 "touch가 조용히 사라진다"였는데,
  이제 위험은 **"touch가 조용히 돌아온다"**다. `test_std_three_rounds`가 그 방향으로
  재작성됐다 — 무변경 페이지는 `bulk_write`가 0이어야 하고, 동시에 `skipped == 4`여야 한다
  ("아무것도 안 썼다"와 "아무것도 못 봤다"는 구분 가능해야 한다).

## 재검토 조건

- 조회수 최신성 부재가 제품 이슈로 올라올 때 — 그때는 조회수 전용 저빈도 배치를 검토.
- 소스 수가 크게 늘어 "실제로 움직이는 행"만으로도 틱당 쓰기가 다시 수백 건이 될 때.
