# Notice Schema

## MongoDB Document

실제 dataclass 정의는 `py/src/skkuverse_crawler/modules/notices/models.py`의 `Notice`. 필드 이름은 camelCase로 저장된다.

```python
@dataclass
class Notice:
    articleNo: int            # 게시글 번호 (SKKU 원본, 학과 내에서만 unique)
    title: str                # 제목
    category: str             # 카테고리 (전략별로 빈 문자열 가능)
    author: str               # 작성자 (전략별로 빈 문자열 가능)
    department: str           # 학과/부서 이름 (한글)
    date: str                 # 작성일 YYYY-MM-DD 문자열
    views: int                # 조회수 (전략별로 0 가능)
    content: str | None       # 원본 HTML + 절대 URL (`normalize_content_urls`)
    contentText: str | None   # cleanHtml 기반 plain text (블록 경계 개행 보존)
    cleanHtml: str | None     # nh3 화이트리스트 HTML (5MB 초과 시 null)
    attachments: list[dict]   # [{"name": str, "url": str, "referer"?: str}]
    sourceUrl: str            # 원본 상세 페이지 URL
    detailPath: str           # 내부 재크롤용 (앱 노출 불필요)
    sourceId: str         # sources.json의 id (e.g. "skku-main")
    cleanMarkdown: str | None # cleanHtml → GFM 변환 결과 (None 가능)
    crawledAt: datetime       # 마지막 크롤링 시각 (UTC)
    lastModified: str | None  # 예약 필드 (현재 미사용)
    contentHash: str | None   # cleanHtml SHA256 (null = 컨텐츠 없음)
    editHistory: list[dict]   # 최근 20개 수정 이력
    editCount: int            # 수정 횟수
    isDeleted: bool           # soft delete (원본 사라짐)
    consecutiveFailures: int  # 상세 fetch 실패 연속 카운트
```

요약 프로세서가 추가로 덧붙이는 필드(`summary`, `summaryOneLiner`, `summaryPeriods`, `summaryLocations`, …)는 `docs/api-design-reference.md` §2.2 참고.

## Index

- Unique compound: `{ articleNo: 1, sourceId: 1 }`
- 같은 articleNo라도 sourceId가 다르면 별개 문서 (학과별 공지는 articleNo 체계가 다를 수 있음)

## 본��� 필드 4종

| 필드 | 내용 | 용도 |
|---|---|---|
| `content` | 원본 HTML + 절대 URL (태그/클래스/스타일 전부 보존) | 레거시 웹뷰 렌더링. 소급 재가공의 입력은 더 이상 이 필드가 아니다 — `repair-dimensions`는 `cleanHtml`/`cleanMarkdown`에서 되짚는다 (§소급 업데이트) |
| `cleanHtml` | `content`를 6단계 파이프라인으로 정제한 HTML. nh3 화이트리스트 적용 | 앱/서버에서 안전하게 렌더 가능한 HTML |
| `cleanMarkdown` | `cleanHtml`을 markdownify + 전처리로 변환한 GFM | 모바일 앱 마크다운 렌더링의 권장 소스 |
| `contentText` | `cleanHtml`에서 블록 경계 개행(`\n`)을 보존하며 추출한 plain text | 검색/AI 요약 입력/미리보기 |

fetch 실패 시 `content` / `cleanHtml` / `cleanMarkdown` 모두 `None` → 다음 크롤링에서 재시도 대상. `contentText`는 strategy fallback으로 채워질 수 있음.

## `attachments[]`

| 키 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `name` | `str` | 항상 | 원본 파일명 그대로 (한글·공백 포함, URL 인코딩 안 됨) |
| `url` | `str` | 항상 | **절대 URL**. host는 `skku.edu` / `skkumed.ac.kr` suffix |
| `referer` | `str` | **일부 전략만** | 상세 페이지 URL. 서버 프록시가 다운로드 요청에 `Referer` 헤더로 실어 보낸다 |

`referer`는 **다운로드 엔드포인트가 Referer를 검증하는 전략**에만 붙는다 — `validation.py`의 `REFERER_REQUIRED_STRATEGIES` (`gnuboard`, `gnuboard-custom`, `custom-php`)가 목록의 진실 원천이고, `validate-attachments`가 누락을 `missing_referer`로 잡는다.

없으면 무슨 일이 나는지가 중요하다: **에러가 아니라 200이 온다.** cal의 NFUpload는 Referer 없는 요청에 `alert("Access denied!!")` HTML을 200으로 돌려주므로, 소비자 입장에서는 "다운로드는 됐는데 파일이 아닌" 상태가 된다 ([known-issues §12](known-issues.md)). 서버 프록시는 저장된 `referer`가 있을 때만 헤더를 붙이므로, 이 필드가 비면 프록시가 할 수 있는 일이 없다.

`size`는 존재하지 않는다 — 어떤 전략도 파일 크기를 저장하지 않는다.

## 크기 특성 (prod 기준 실측)

- `content`: 학과별 편차 큼 (원본 HTML 그대로라 WP 사이트는 MB 단위 가능)
- `cleanHtml`: 평균 ~6KB, max 수백 KB
- `cleanMarkdown`: 평균 ~1.2KB, max ~6.3KB
- `contentText`: cleanMarkdown과 비슷한 수준

→ 리스트 응답에선 `content`/`cleanHtml`/`cleanMarkdown` 제외 권장, 상세 응답에서만 포함.

## Upsert 동작

- `articleNo + sourceId` 기준으로 upsert
- 이미 존재하면 전체 필드를 `$set`으로 덮어씀
- 1페이지 글은 매번 upsert → 제목/내용 수정이 자동 반영

## 소급 업데이트 (backfill)

**`backfill-content` 커맨드는 없어졌다** (adr-006 리팩터). 소급 갱신은 두 경로로 갈렸다:

| 대상 | 경로 |
|------|------|
| `content: null`인 문서 재크롤 | **크롤에 흡수됨.** `plugins/mongo/work_seed.py`가 매 크롤 시작 시 `pending_refs()`로 대상을 뽑고, 상세 재fetch 결과가 `ContentRefreshed` 이벤트로 흐른다. mode 무관, 별도 커맨드 없음 |
| 파이프라인 개선분 소급 반영 | **일회성.** 필요할 때만 전용 커맨드를 만들고, 대상 모집단이 0이 되면 지운다. 현행 사례가 `repair-dimensions` (`plugins/mongo/repair.py` — tier-2가 지운 이미지 차원 복구, 멱등) |

`backfilledAt` 필드도 함께 폐지됐다 — 쓰는 코드가 없고, 프로덕션 6,891건 중 보유 문서 0건 (2026-08-04 확인).

## crawl_health 컬렉션

크롤 헬스 알림용 소스 단위 상태 (sourceId당 1건, `plugins/health/store.py`가 upsert):

```javascript
{
  sourceId: "sls-special",
  sourceName: "법학전문대학원",
  consecutiveFailures: 3,        // page-0 list fetch 연속 실패 틱 수
  lastFailureAt: ISODate,
  lastError: "Client error '404 ...'",  // 500자 truncate
  lastSuccessAt: ISODate,
  alerted: true,                 // 장애당 1회 발화 래치 — 회복 시 false로 리셋
  updatedAt: ISODate
}
```

매 notices 틱마다 전 소스 upsert. DB에 있으므로 컨테이너 재배포에도 카운트 연속. 판정 로직은 `plugins/health/logic.py::decide_transitions` (순수 함수).
