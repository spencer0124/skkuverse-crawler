# jsp-dorm 전략: SKKU 기숙사 게시판 (Type F)

## 사이트 개요

| 항목 | 명륜학사 (인사캠) | 봉룡학사 (자과캠) |
|------|-------------------|-------------------|
| URL | `https://dorm.skku.edu/dorm_seoul/notice/notice_all.jsp` | `https://dorm.skku.edu/dorm_suwon/notice/notice_all.jsp` |
| board_no | `78` | `16` |
| siteId | `dorm_seoul` | `dorm_suwon` |
| CMS 루트 클래스 | `notice_seoul-board` | `notice-board` |
| 분류(카테고리) | 일반, Notice in English, 공통, 입/퇴사 | 일반, 식당, 입/퇴사, Notice in English |
| 페이지당 항목 | 10 (+ 상단공지) | 10 (+ 상단공지) |

동일한 SKKU JSP 게시판 엔진(`/_custom/skku/_common/board/`)을 사용하며, HTML 구조가 **완전히 동일**하다.
`skku-standard` 전략(dl/dt/dd 구조)과는 완전히 다른 table 기반 레이아웃을 사용한다.

## 목록 페이지 HTML 구조

### 전체 레이아웃

```
div#jwxe_main_content
  └─ div.jwxe_root.jwxe_board
       ├─ div.search_wrap          ← 검색 폼
       ├─ div.list_wrap[lng="ko"]  ← 목록 테이블 래퍼
       │    └─ table.list_table
       │         ├─ thead > tr > th (No, 분류, 제목, 파일, 등록일, 조회수)
       │         └─ tbody > tr     ← 각 게시글
       ├─ div.btn_wrap             ← 글쓰기 버튼 (비로그인 시 비어있음)
       └─ div.paging               ← 페이지네이션
```

### 목록 URL 패턴

```
{baseUrl}?mode=list&board_no={board_no}&pager.offset={offset}
```

- `offset` = 0, 10, 20, ... (페이지 번호 × 10)
- 첫 페이지: offset 파라미터 없이 `notice_all.jsp`로도 접근 가능

### 테이블 구조 (thead)

```html
<table class="list_table">
  <thead>
    <tr>
      <th scope="col" class="th">No</th>
      <th scope="col" class="th th_back">분류</th>
      <th scope="col" class="th th_back">제목</th>
      <th scope="col" class="th th_back">파일</th>
      <th scope="col" class="th th_back">등록일</th>
      <th scope="col" class="th th_back">조회수</th>
    </tr>
  </thead>
```

### 일반 게시글 행 (tbody > tr)

```html
<tr class="row-bg">   <!-- 또는 class 없음 (줄 번갈아 배경색) -->
  <td class="td">1041</td>                    <!-- td[0]: 순번 -->
  <td class="td">Notice in English</td>       <!-- td[1]: 분류 -->
  <td class="td title">                       <!-- td[2]: 제목 + 링크 -->
    <a href="?mode=view&amp;article_no=86125&amp;board_wrapper=%2Fdorm_seoul%2Fnotice%2Fnotice_all.jsp&amp;pager.offset=0&amp;board_no=78&no=1041">
      제목 텍스트
    </a>
    <!-- (선택) 최신 글 표시 -->
    <img src="/_custom/skku/_common/board/common/img/icon/ico_new.gif" alt="최신게시물표시 이미지"/>
  </td>
  <td class="td">&nbsp;                        <!-- td[3]: 첨부파일 아이콘 -->
    <!-- 첨부파일 있을 때: -->
    <img src="/_custom/skku/_common/board/common/img/icon/file_icon.gif" alt="파일명.pdf"/>
  </td>
  <td class="td">2026-03-16</td>              <!-- td[4]: 등록일 -->
  <td class="td">144</td>                     <!-- td[5]: 조회수 -->
</tr>
```

### 상단공지(고정글) 행 구조

```html
<tr style="background:#f4f4f4;">               <!-- 인라인 스타일로 배경색 지정 -->
  <td class="td" style="text-align:center">
    <img src="/_custom/skku/_common/board/common/img/notice_icon.png" alt="상단공지" />
  </td>                                        <!-- td[0]: 순번 대신 아이콘 -->
  <td class="td">일반</td>                     <!-- td[1]: 분류 -->
  <td class="td title">                        <!-- td[2]: 제목 + 링크 -->
    <a href="?mode=view&amp;article_no=85588&amp;...">제목</a>
  </td>
  <td class="td">&nbsp;</td>                   <!-- td[3]: 첨부파일 -->
  <td class="td">2026-02-12</td>              <!-- td[4]: 등록일 -->
  <td class="td">4916</td>                    <!-- td[5]: 조회수 -->
</tr>
```

**상단공지 판별 기준:**
- `tr[style*="background:#f4f4f4"]` 인라인 스타일
- td[0]에 `img[alt="상단공지"]` 이미지 존재 (순번 숫자 대신)
- **모든 페이지에서 반복 출력됨** (중복 주의!)
  - 서울: 상단공지 1건 + 일반 10건 = 11건/페이지
  - 수원: 상단공지 9건 + 일반 10건 = 19건/페이지

### CSS 셀렉터 요약 (목록)

| 용도 | 셀렉터 |
|------|--------|
| 게시글 행 전체 | `table.list_table tbody tr` |
| 일반 게시글만 (상단공지 제외) | `table.list_table tbody tr:not([style*="background:#f4f4f4"])` |
| 상단공지만 | `table.list_table tbody tr[style*="background:#f4f4f4"]` |
| 제목 링크 | `td.title a` |
| 분류 | tr 내 `td:nth-child(2)` |
| 등록일 | tr 내 `td:nth-child(5)` |
| 조회수 | tr 내 `td:nth-child(6)` |
| 순번 | tr 내 `td:nth-child(1)` (상단공지는 숫자 아닌 이미지) |

## article_no 추출

### href 패턴

```
?mode=view&article_no={articleNo}&board_wrapper={urlEncodedPath}&pager.offset={offset}&board_no={boardNo}&no={sequenceNo}
```

### 추출 정규식

```python
match = re.search(r"article_no=(\d+)", href)
article_no = int(match.group(1)) if match else None
```

**주의:** `skku-standard`는 `articleNo` (camelCase), JSP 기숙사는 `article_no` (snake_case).

### detailPath 구성

목록에서 추출한 href를 그대로 `detailPath`로 저장:
```
?mode=view&article_no=85588&board_wrapper=%2Fdorm_seoul%2Fnotice%2Fnotice_all.jsp&pager.offset=0&board_no=78&no=1042
```

상세 페이지 URL = `baseUrl` + `detailPath`:
```
https://dorm.skku.edu/dorm_seoul/notice/notice_all.jsp?mode=view&article_no=85588&board_wrapper=...
```

## 상세 페이지 HTML 구조

### 전체 레이아웃

```
div#jwxe_main_content
  └─ div.jwxe_root.jwxe_board
       ├─ div.view_wrap
       │    └─ table.view_table
       │         ├─ tr > td.td.title (colspan=4)    ← 제목 ([카테고리] 제목)
       │         ├─ tr > td.th (colspan=4)           ← 메타 (번호, 등록일, 조회수)
       │         ├─ tr (첨부파일, 조건부)              ← 첨부파일 영역
       │         └─ tr > td (colspan=4)              ← 본문
       │              └─ div#article_text             ← 본문 컨텐츠
       ├─ table.next_table                            ← 이전글/다음글
       └─ div.btn_wrap                                ← 목록 버튼
```

### 제목 영역

```html
<tr>
  <td colspan="4" class="td title ">
    [일반]
    2026. 1학기 오리엔테이션 및 소방 안전교육
  </td>
</tr>
```

- 셀렉터: `table.view_table td.title`
- 카테고리가 `[카테고리명]` 형태로 제목 앞에 포함됨
- 상세 페이지에서 제목을 파싱할 필요는 보통 없음 (목록에서 이미 추출)

### 메타 정보 영역

```html
<tr style="height:35px;">
  <td scope="row" class="th" colspan="4">
    <span class="bold">번호 :</span>  <span class="r_linen" style="padding-right:15px;"></span>
    <span class="bold">등록일 :</span>  <span class="r_linen">2026-03-04</span>
    <span class="bold">조회수 :</span> 551
  </td>
</tr>
```

- 번호(`No`) 값은 실제로 비어있음 (span.r_linen 내부 텍스트 없음)
- 등록일과 조회수는 목록에서도 파싱 가능하므로 상세 페이지에서 추출할 필요 없음

### 첨부파일 영역

```html
<!-- 첨부파일이 있을 때만 이 tr이 렌더링됨 -->
<tr style="height:35px;">
  <th class="th">
    <span class="bold">첨부파일</span>
    <span class="r_linen" style="margin-left:12px;"></span>
  </th>
  <td class="th" colspan="3" style="padding:15px 0px 10px 0px;">
    <div style="margin-bottom:5px;">
      <a href="/_custom/skku/_common/board/download.jsp?attach_no=7376&article_no=85566"
         title="Guidance_for_Paying dormitory fee.pdf 다운로드">
        <img class="attach-icon" src="/skku/_res/img/board_icon/file.png" ... />
        Guidance_for_Paying dormitory fee.pdf
      </a>
    </div>
    <!-- 파일이 여러 개면 div 반복 -->
  </td>
</tr>
```

- 셀렉터: `table.view_table th:contains("첨부파일") + td a` 또는 더 안정적으로:
  ```
  table.view_table a[href*="download.jsp"]
  ```
- 다운로드 URL 패턴: `/_custom/skku/_common/board/download.jsp?attach_no={attachNo}&article_no={articleNo}`
- 파일명: `<a>` 태그의 텍스트에서 추출 (img 제외)

### 본문 영역

```html
<tr>
  <td class="td" colspan="4">
    <div id="article_text" style="margin-left:0;">
      <!-- HTML 본문 (p, div, span, table, img 등) -->
    </div>
  </td>
</tr>
```

- **셀렉터: `div#article_text`**
- `content` = `$('#article_text').html()`
- `contentText` = `$('#article_text').text().trim()`
- 본문에 포함된 이미지 src 패턴: `/_attach/editor_image/YYYY-MM/랜덤문자열.png`

### CSS 셀렉터 요약 (상세)

| 용도 | 셀렉터 |
|------|--------|
| 본문 컨텐츠 | `div#article_text` |
| 첨부파일 목록 | `table.view_table a[href*="download.jsp"]` |
| 제목 | `table.view_table td.title` |
| 이전/다음 글 | `table.next_table a` |

## 페이지네이션

### 구조

```html
<div class="paging">
  <span class="on"><strong>1</strong></span>   <!-- 현재 페이지 -->
  <span><a href="/dorm_seoul/notice/notice_all.jsp?mode=list&board_no=78&pager.offset=10">2</a></span>
  <span><a href="...&pager.offset=20">3</a></span>
  <!-- ... -->
  <span><a href="...&pager.offset=90">10</a></span>

  <!-- 다음 페이지 그룹 -->
  <a href="...&pager.offset=10">
    <img src="/_custom/skku/_common/board/common/img/btn/btn_page_next.gif" alt="다음으로 이동" class="next"/>
  </a>

  <!-- 마지막 페이지 -->
  <a href="...&pager.offset=1040">
    <img src="/_custom/skku/_common/board/common/img/btn/btn_page_last.gif" alt="마지막으로 이동"/>
  </a>
</div>
```

### 메커니즘

| 항목 | 값 |
|------|-----|
| 페이지네이션 타입 | offset 기반 |
| offset 파라미터 | `pager.offset` |
| 페이지당 항목 수 | 10 (고정글 제외) |
| offset 공식 | `page * 10` (0, 10, 20, ...) |
| 현재 페이지 표시 | `span.on > strong` (링크 없음) |
| 빈 tbody 시 | 마지막 페이지 도달 (항목 0개) |

### 마지막 페이지 판별

1. **방법 A (권장):** tbody 내 일반 게시글(`tr:not([style*="background:#f4f4f4"])`) 개수가 0이면 마지막
2. **방법 B:** 마지막 페이지 링크(`img[alt="마지막으로 이동"]`)의 `pager.offset` 값을 확인하여 총 페이지 수 계산

## skku-standard와의 차이점

| 항목 | skku-standard (Type A/B/H) | jsp-dorm (Type F) |
|------|---------------------------|-------------------|
| 게시판 엔진 | SKKU 표준 CMS (.do) | SKKU JSP 보드 (.jsp) |
| 목록 구조 | `dl > dt + dd` (리스트) | `table > tbody > tr > td` (테이블) |
| 제목 셀렉터 | `dt.board-list-content-title a` | `td.title a` |
| articleNo 파라미터 | `articleNo` (camelCase) | `article_no` (snake_case) |
| 메타 위치 | `dd.board-list-content-info ul li` | 테이블의 각 td (인덱스 기반) |
| 작성자 | 목록에서 추출 가능 | **목록/상세 모두에서 제공하지 않음** |
| 본문 셀렉터 | `dl.board-write-box dd` | `div#article_text` |
| 첨부파일 | `ul.filedown_list li a` | `a[href*="download.jsp"]` |
| offset 파라미터 | `article.offset` | `pager.offset` |
| 상단공지 | 별도 표시 없음 | `style="background:#f4f4f4"` + 아이콘 |
| 상단공지 중복 | 없음 | **모든 페이지에서 반복됨** |

## 크롤링 시 주의사항

### 1. 상단공지 중복 처리 (매우 중요)

상단공지(고정글)는 **모든 목록 페이지에서 반복**된다.
수원(봉룡학사)은 상단공지가 9건이므로 페이지마다 9건이 중복 출현한다.

**처리 방안:**
- `tr[style*="background:#f4f4f4"]` 행은 파싱에서 **제외**하고, 첫 페이지에서만 별도 수집
- 또는: 모든 행을 파싱하되 `upsert` (articleNo 기준)로 중복 자동 해소
- **추천:** 상단공지 행을 필터링하여 제외. 상단공지의 articleNo는 별도로 1회만 수집

### 2. 작성자(author) 부재

목록과 상세 페이지 모두에서 **작성자 정보를 제공하지 않는다**.
Notice 스키마의 `author` 필드는 빈 문자열 `''`로 설정해야 한다.

### 3. article_no vs articleNo

기존 `skku-standard` 전략은 URL에서 `articleNo`(camelCase)를 추출한다.
JSP 기숙사 게시판은 `article_no`(snake_case)를 사용한다.
정규식을 `article_no=(\d+)` 또는 `article[_]?[Nn]o=(\d+)`로 대응해야 한다.

### 4. board_wrapper 파라미터

상세 페이지 URL에 `board_wrapper` 파라미터가 필수이다.
목록에서 추출한 href를 그대로 `detailPath`로 저장하면 자동으로 포함된다.

### 5. 인코딩

페이지 인코딩은 `UTF-8`이다 (`<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />`).
특수문자는 HTML 엔티티로 이스케이프됨 (`&amp;`, `&#40;`, `&#41;` 등).

## 전략 구현 (구현 완료)

### 관련 파일

- `py/src/skkuverse_crawler/notices/strategies/jsp_dorm.py` — `crawl_list()` + `crawl_detail()` 구현
- `py/src/skkuverse_crawler/notices/types.py` — `JspDormConfig` TypedDict
- `py/src/skkuverse_crawler/notices/config/departments.json` — dorm-hssc, dorm-nsc 설정

## 두 캠퍼스의 구조적 동일성

| 비교 항목 | 서울 (명륜학사) | 수원 (봉룡학사) | 동일 여부 |
|-----------|----------------|----------------|----------|
| 게시판 엔진 | JSP board | JSP board | 동일 |
| table.list_table 구조 | 6열 (No/분류/제목/파일/등록일/조회수) | 6열 (동일) | 동일 |
| 상단공지 마크업 | `style="background:#f4f4f4"` + notice_icon.png | 동일 | 동일 |
| href 패턴 | `?mode=view&article_no=...&board_wrapper=...&board_no=78` | `?mode=view&article_no=...&board_wrapper=...&board_no=16` | board_no만 다름 |
| 상세 view_table 구조 | td.title → td.th(메타) → 첨부 → div#article_text | 동일 | 동일 |
| 첨부파일 구조 | download.jsp?attach_no=...&article_no=... | 동일 | 동일 |
| 페이지네이션 | pager.offset, 10 per page | 동일 | 동일 |
| 인코딩 | UTF-8 | UTF-8 | 동일 |

**결론: 하나의 `jsp-dorm` 전략으로 두 캠퍼스 모두 커버 가능하다.**
차이점은 `baseUrl`, `boardNo`, `id`, `name`뿐이며, 이는 departments.json에서 설정한다.

## departments.json 설정 예시

```json
[
  {
    "id": "dorm-hssc",
    "name": "명륜학사 (인사캠 기숙사)",
    "strategy": "jsp-dorm",
    "baseUrl": "https://dorm.skku.edu/dorm_seoul/notice/notice_all.jsp",
    "boardNo": "78",
    "selectors": {
      "listRow": "table.list_table tbody tr",
      "pinnedRow": "table.list_table tbody tr[style*=\"background:#f4f4f4\"]",
      "titleLink": "td.title a",
      "detailContent": "div#article_text",
      "attachmentLink": "table.view_table a[href*=\"download.jsp\"]"
    },
    "pagination": {
      "type": "offset",
      "param": "pager.offset",
      "limit": 10
    }
  },
  {
    "id": "dorm-nsc",
    "name": "봉룡학사 (자과캠 기숙사)",
    "strategy": "jsp-dorm",
    "baseUrl": "https://dorm.skku.edu/dorm_suwon/notice/notice_all.jsp",
    "boardNo": "16",
    "selectors": {
      "listRow": "table.list_table tbody tr",
      "pinnedRow": "table.list_table tbody tr[style*=\"background:#f4f4f4\"]",
      "titleLink": "td.title a",
      "detailContent": "div#article_text",
      "attachmentLink": "table.view_table a[href*=\"download.jsp\"]"
    },
    "pagination": {
      "type": "offset",
      "param": "pager.offset",
      "limit": 10
    }
  }
]
```

## config/loader.py 검증 규칙

`jsp-dorm` 전략의 필수 셀렉터: `listRow`, `pinnedRow`, `titleLink`, `detailContent`, `attachmentLink`.

추가 필수 필드: `boardNo` (문자열).

## 참고: 검색 폼 구조

크롤러에서 검색 기능을 사용할 필요는 없지만, 참고용으로 기록:

```html
<form class="search_form" method="get" action="">
  <input type="hidden" name="board_no" value="78"/>
  <select name="search:search_category:category">
    <option value="">분류선택</option>
    <option value="104">일반</option>
    <option value="103">Notice in English</option>
    <!-- ... -->
  </select>
  <select name="search:search_key:search_or">
    <option value="article_title">제목</option>
    <option value="article_text">내용</option>
    <option value="article_title">제목+내용</option>
  </select>
  <input type="hidden" name="search:search_key2:search_or" value="article_text" />
  <input type="text" name="search:search_val:search_or" value="" />
</form>
```

검색 파라미터는 `search:search_key:search_or`, `search:search_val:search_or` 등 콜론 구분자를 사용하는 독특한 네이밍 컨벤션이다.
