# Notice Schema

## MongoDB Document

```python
@dataclass
class Notice:
    article_no: int           # 게시글 번호 (SKKU 원본)
    title: str                # 제목
    category: str             # 카테고리 (행사/세미나, 채용/모집 등)
    author: str               # 작성자
    department: str           # 학과/부서 이름 (한글)
    date: str                 # 작성일 YYYY-MM-DD
    last_modified: str | None # 최종 수정일
    views: int                # 조회수
    content: str | None       # 본문 HTML (fetch 실패 시 None)
    content_text: str | None  # 본문 plain text (bs4 .get_text())
    attachments: list[dict]   # 첨부파일 목록 [{"name": str, "url": str}]
    source_url: str           # 원본 상세 페이지 URL
    source_dept_id: str       # departments.json의 id (e.g. "skku-main")
    crawled_at: datetime      # 크롤링 시각
```

## Index

- Unique compound: `{ articleNo: 1, sourceDeptId: 1 }`
- 같은 articleNo라도 sourceDeptId가 다르면 별개 문서 (학과별 공지는 articleNo 체계가 다를 수 있음)

## content vs contentText

- `content`: 원본 HTML (이미지 태그, 링크 등 보존)
- `contentText`: BeautifulSoup `.get_text()`로 추출한 순수 텍스트 (검색/요약용)
- fetch 실패 시 둘 다 `None` → 다음 크롤링에서 재시도 대상

## Upsert 동작

- `articleNo + sourceDeptId` 기준으로 upsert
- 이미 존재하면 전체 필드를 `$set`으로 덮어씀
- 1페이지 글은 매번 upsert → 제목/내용 수정이 자동 반영
