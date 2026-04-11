# Notice Schema

## MongoDB Document

실제 dataclass 정의는 `py/src/skkuverse_crawler/notices/models.py:26-49`. 필드 이름은 camelCase로 저장된다.

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
    attachments: list[dict]   # [{"name": str, "url": str}]
    sourceUrl: str            # 원본 상세 페이지 URL
    detailPath: str           # 내부 재크롤용 (앱 노출 불필요)
    sourceDeptId: str         # departments.json의 id (e.g. "skku-main")
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

- Unique compound: `{ articleNo: 1, sourceDeptId: 1 }`
- 같은 articleNo라도 sourceDeptId가 다르면 별개 문서 (학과별 공지는 articleNo 체계가 다를 수 있음)

## 본문 필드 3종

| 필드 | 내용 | 용도 |
|---|---|---|
| `content` | 원본 HTML + 절대 URL (태그/클래스/스타일 전부 보존) | 레거시 웹뷰 렌더링. backfill 시 `clean_html()` 재투입 입력 소스 (idempotent) |
| `cleanHtml` | `content`를 6단계 파이프라인으로 정제한 HTML. nh3 화이트리스트 적용 | 앱/서버에서 안전하게 렌더 가능한 HTML |
| `cleanMarkdown` | `cleanHtml`을 markdownify + 전처리로 변환한 GFM | 모바일 앱 마크다운 렌더링의 권장 소스 |
| `contentText` | `cleanHtml`에서 블록 경계 개행(`\n`)을 보존하며 추출한 plain text | 검색/AI 요약 입력/미리보기 |

fetch 실패 시 `content` / `cleanHtml` / `cleanMarkdown` 모두 `None` → 다음 크롤링에서 재시도 대상. `contentText`는 strategy fallback으로 채워질 수 있음.

## 크기 특성 (prod 기준 실측)

- `content`: 학과별 편차 큼 (원본 HTML 그대로라 WP 사이트는 MB 단위 가능)
- `cleanHtml`: 평균 ~6KB, max 수백 KB
- `cleanMarkdown`: 평균 ~1.2KB, max ~6.3KB
- `contentText`: cleanMarkdown과 비슷한 수준

→ 리스트 응답에선 `content`/`cleanHtml`/`cleanMarkdown` 제외 권장, 상세 응답에서만 포함.

## Upsert 동작

- `articleNo + sourceDeptId` 기준으로 upsert
- 이미 존재하면 전체 필드를 `$set`으로 덮어씀
- 1페이지 글은 매번 upsert → 제목/내용 수정이 자동 반영

## 소급 업데이트 (backfill)

파이프라인 개선(`clean_html`, `_text_from_clean_html`, `html_to_markdown`) 을 기존 문서에 반영하려면:

```bash
python -m skkuverse_crawler backfill-content             # dry-run
python -m skkuverse_crawler backfill-content --apply     # 실행
```

`content` 필드를 재크롤 없이 재가공. 업데이트한 문서에는 `backfilledAt: datetime(UTC)` 필드가 찍힌다(신규 크롤 문서엔 없음 — backfill 전용 마커).
