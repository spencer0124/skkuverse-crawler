# Gnuboard / PHP 게시판 크롤링 전략

## 개요

SKKU 학과 홈페이지 중 PHP 기반 게시판을 사용하는 사이트를 크롤링하기 위한 전략 문서.
크게 **두 가지 서브타입**으로 나뉜다:

| 서브타입 | 설명 | 게시판 엔진 | 사용 학과 |
|---------|------|-----------|----------|
| **C1** | 커스텀 PHP 게시판 | 자체 PHP (Naver SmartEditor 연동) | 건설환경공학부 |
| **C2-gnuboard** | 그누보드5 기반 | Gnuboard5 (다양한 스킨) | 생명과학과, 약학대학 |
| **C2-custom** | 그누보드 유사 커스텀 | GnCommon 솔루션 (tbl 파라미터) | 나노공학과 |

**결론: C1, C2-gnuboard, C2-custom은 각각 별도 전략이 필요하다.** URL 구조, 셀렉터, 파라미터명이 모두 다르다.

---

## Sub-type C1: 커스텀 PHP (cal.skku.edu)

### 대상 사이트

- `https://cal.skku.edu/index.php?hCode=BOARD&bo_idx=17` (건설환경공학부 학부생)
- `https://cal.skku.edu/index.php?hCode=BOARD&bo_idx=18` (건설환경공학부 대학원)

### 인코딩

- UTF-8 (meta charset 명시)

### 목록 페이지 HTML 구조

테이블 기반. `#con_area` 내부에 `<table>` 사용. 별도의 ID/class가 없는 단순 `<table>` 태그.

```html
<div id="con_area">
  <table>
    <!-- thead 없음 — 바로 tr 시작 -->
    <tr>
      <td>공지</td>           <!-- 공지 여부 (일반 글은 번호) -->
      <td>취업</td>           <!-- 카테고리 -->
      <td>
        <a href="?page=view&pg=&idx=1302&hCode=BOARD&bo_idx=17">
          [GS칼텍스] 2026년 상반기...
        </a>
      </td>                   <!-- 제목 + 링크 -->
      <td>109</td>            <!-- 조회수 -->
      <td>2026-03-24</td>     <!-- 날짜 (YYYY-MM-DD) -->
    </tr>
  </table>
</div>
```

**컬럼 순서 (td index):**

| index | 내용 | 비고 |
|-------|------|------|
| 0 | 번호/공지 | "공지" 텍스트면 공지글, 숫자면 일반글 |
| 1 | 카테고리 | 취업, 장학, 학사, 일반 등 |
| 2 | 제목 + 링크 | `<a>` 태그 포함 |
| 3 | 조회수 | 숫자 (일부 행에 `<img>` 첨부파일 아이콘 포함 가능) |
| 4 | 날짜 | YYYY-MM-DD |

**주의**: bo_idx=18 (대학원)에는 td 인덱스 3에 첨부파일 아이콘 `<img>` 컬럼이 추가될 수 있다.
bo_idx=18 구조:

| index | 내용 |
|-------|------|
| 0 | 번호/공지 |
| 1 | 카테고리 |
| 2 | 제목 + 링크 |
| 3 | 첨부파일 아이콘 (`<img src="./images/common/icon_pdf.jpg">`) |
| 4 | 조회수 |
| 5 | 날짜 |

### articleNo 추출 패턴

```
href="?page=view&pg=&idx={articleNo}&hCode=BOARD&bo_idx={boardId}"
```

- 파라미터명: `idx`
- 예시: `idx=1302`, `idx=1298`
- URL에서 정규식으로 추출: `idx=(\d+)`

### 페이지네이션

```
/index.php?pg={pageNumber}&page=list&hCode=BOARD&bo_idx={boardId}
```

- 파라미터명: `pg`
- 1-based (pg=1, pg=2, ...)
- 목록 URL에서 pg 생략 시 1페이지

### 상세 페이지 HTML 구조

```
https://cal.skku.edu/index.php?page=view&idx={articleNo}&hCode=BOARD&bo_idx={boardId}
```

```html
<div id="con_area">
  <table class="board_Vtable">
    <thead>
      <tr>
        <th colspan="3">게시글 제목</th>         <!-- 제목 -->
      </tr>
      <tr>
        <td colspan="3">
          <ul>
            <li>관리자</li>                      <!-- 작성자 -->
            <li class="imbar">|</li>
            <li>110</li>                         <!-- 조회수 -->
            <li class="imbar">|</li>
            <li>2026-03-24 10:52:54</li>         <!-- 날짜 -->
          </ul>
        </td>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td colspan="3">
          <div class="board_content">
            <!-- 본문 HTML -->
          </div>
        </td>
      </tr>
    </tbody>
    <tfoot>
      <tr>
        <td>이전글</td>
        <td colspan="2"><a href="...">이전글 제목</a></td>
      </tr>
      <tr>
        <td>다음글</td>
        <td colspan="2"><a href="...">다음글 제목</a></td>
      </tr>
    </tfoot>
  </table>
</div>
```

**셀렉터 정리:**

| 요소 | CSS 셀렉터 |
|------|-----------|
| 제목 | `table.board_Vtable thead tr:first-child th` |
| 메타 정보 | `table.board_Vtable thead tr:nth-child(2) td ul li` (li[0]=작성자, li[2]=조회수, li[4]=날짜) |
| 본문 컨텐츠 | `div.board_content` |
| 이전/다음 글 | `table.board_Vtable tfoot tr td a` |

**첨부파일**: 상세 페이지에서 별도 첨부파일 섹션 미확인. 본문 HTML 내부에 링크로 포함될 수 있음.

---

## Sub-type C2-gnuboard: 표준 그누보드5

### 대상 사이트

- `http://bio.skku.edu/bbs/board.php?bo_table=N4` (생명과학과 학부생)
- `http://bio.skku.edu/bbs/board.php?bo_table=N5` (생명과학과 대학원)
- `https://pharm.skku.edu/bbs/board.php?bo_table=notice` (약학대학)

### 인코딩

- UTF-8 (`<meta charset="utf-8">` 명시)

### 그누보드5 전역 변수

페이지 `<script>` 태그에서 확인 가능:

```javascript
var g5_url       = "http://bio.skku.edu";
var g5_bbs_url   = "http://bio.skku.edu/bbs";
var g5_bo_table  = "N4";  // 현재 게시판 테이블명
```

### 목록 페이지 HTML 구조

**사이트별로 스킨이 다르다!** 두 가지 스킨 패턴 확인:

#### 패턴 A: 테이블형 스킨 (bio.skku.edu)

스킨: `theme/basic_responsive_new`

```html
<div id="bo_list" style="width:100%">
  <form name="fboardlist" id="fboardlist">
    <div class="spage">
      <table class="table table-bordered">
        <thead>
          <tr>
            <th>번호</th>
            <th>제목</th>
            <th>글쓴이</th>
            <th>조회</th>
            <th>날짜</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td class="text-center">803</td>                    <!-- 번호 -->
            <td style="padding-left:0px">&nbsp;&nbsp;
              <SPAN>
                <a href="http://bio.skku.edu/bbs/board.php?bo_table=N4&amp;wr_id=367">
                  [한국장학재단] 2026년 푸른등대 삼성기부장학금...
                </a>
              </SPAN>
              <i class="fa fa-download" aria-hidden="true"></i>  <!-- 첨부파일 아이콘 -->
            </td>
            <td class="text-center">
              <span class="sv_member">관리자</span>              <!-- 작성자 -->
            </td>
            <td class="text-center">27</td>                     <!-- 조회수 -->
            <td class="text-center">03-26</td>                  <!-- 날짜 (MM-DD) -->
          </tr>
        </tbody>
      </table>
    </div>
  </form>
</div>
```

**셀렉터:**

| 요소 | CSS 셀렉터 |
|------|-----------|
| 게시판 컨테이너 | `#bo_list` |
| 게시글 행 | `#bo_list table.table tbody tr` |
| 번호 | `td:nth-child(1)` |
| 제목 + 링크 | `td:nth-child(2) a` |
| 작성자 | `td:nth-child(3) .sv_member` |
| 조회수 | `td:nth-child(4)` |
| 날짜 | `td:nth-child(5)` |
| 첨부파일 유무 | `td:nth-child(2) i.fa-download` 존재 여부 |

**날짜 형식 주의**: `MM-DD` 형식 (연도 없음). 크롤링 시점의 연도를 추정해야 함.

#### 패턴 B: 리스트형 스킨 (pharm.skku.edu)

스킨: 커스텀 `skkupharm` 테마

```html
<ol class="bo_lst" id="board_list">
  <li>
    <a href="//pharm.skku.edu/bbs/board.php?bo_table=notice&amp;wr_id=2688" title="내용보기">
      <article class="bo_info">
        <h2>
          <span class="category">공지</span>
          2026학년도 총동창회 글로벌센터 1억클럽(송천류덕희장학금) 장학생 모집 안내
        </h2>
        <p>
          <span class="write">관리자</span>
          <span class="time">2026-03-26</span>
        </p>
        <span class="lst_file" title="첨부파일">첨부파일</span>
      </article>
    </a>
  </li>
</ol>
```

**셀렉터:**

| 요소 | CSS 셀렉터 |
|------|-----------|
| 게시판 컨테이너 | `ol.bo_lst#board_list` |
| 게시글 항목 | `ol.bo_lst > li` |
| 제목 + 링크 | `li > a` (href에 wr_id 포함) |
| 제목 텍스트 | `article.bo_info h2` |
| 공지 여부 | `span.category` 텍스트가 "공지" |
| 작성자 | `span.write` |
| 날짜 | `span.time` (YYYY-MM-DD) |
| 첨부파일 유무 | `span.lst_file` 존재 여부 |

**특이사항**: `<a>` 태그가 `<li>` 전체를 감싸며, href가 `//pharm.skku.edu/...` (프로토콜 상대 URL).

### articleNo 추출 패턴

```
href="...board.php?bo_table={boardName}&wr_id={articleNo}"
```

- 파라미터명: `wr_id`
- 예시: `wr_id=367`, `wr_id=2688`
- URL에서 정규식으로 추출: `wr_id=(\d+)`

### 페이지네이션

```html
<nav class="pg_wrap">
  <span class="pg">
    <strong class="pg_current">1</strong>
    <a href=".../board.php?bo_table=N4&amp;page=2" class="pg_page">2</a>
    <a href=".../board.php?bo_table=N4&amp;page=11" class="pg_page pg_next">다음</a>
    <a href=".../board.php?bo_table=N4&amp;page=81" class="pg_page pg_end">맨끝</a>
  </span>
</nav>
```

- 파라미터명: `page`
- 1-based (page=1, page=2, ...)
- 현재 페이지: `strong.pg_current`
- 다음 페이지: `a.pg_next`
- 마지막 페이지: `a.pg_end`
- 마지막 페이지 번호로 총 페이지 수 계산 가능

### 상세 페이지 HTML 구조

```
http://bio.skku.edu/bbs/board.php?bo_table=N4&wr_id=367
https://pharm.skku.edu/bbs/board.php?bo_table=notice&wr_id=2688
```

**두 사이트 모두 동일한 그누보드5 상세 페이지 구조 사용:**

```html
<article id="bo_v">
  <header>
    <h2 id="bo_v_title">
      <span class="bo_v_tit">게시글 제목</span>
    </h2>
  </header>

  <section id="bo_v_info">
    <strong><span class="sv_member">관리자</span></strong>           <!-- 작성자 -->
    <strong><i class="fa fa-eye"></i> 27회</strong>                  <!-- 조회수 -->
    <strong class="if_date"><i class="fa fa-clock-o"></i> 26-03-26 10:15</strong>  <!-- 날짜 -->
  </section>

  <section id="bo_v_atc">
    <div id="bo_v_con">
      <!-- 본문 HTML 컨텐츠 -->
    </div>
  </section>

  <!-- 첨부파일 (선택적) -->
  <section id="bo_v_file">
    <ul>
      <li>
        <a href=".../download.php?bo_table=N4&amp;wr_id=367&amp;no=0" class="view_file_download">
          <strong>파일명.pdf</strong>
        </a>
        (1.1M)
        <span class="bo_v_file_cnt">3회 다운로드 | DATE : 2026-03-26 10:17:12</span>
      </li>
    </ul>
  </section>

  <!-- 이전/다음 글 -->
  <ul class="bo_v_nb">
    <li class="btn_next">
      <span class="nb_tit">다음글</span>
      <a href="...&wr_id=366">다음글 제목</a>
      <span class="nb_date">26.03.19</span>
    </li>
  </ul>
</article>
```

**상세 페이지 셀렉터 (공통):**

| 요소 | CSS 셀렉터 |
|------|-----------|
| 제목 | `#bo_v_title .bo_v_tit` 또는 `header h1` (pharm) |
| 본문 컨텐츠 | `#bo_v_con` |
| 첨부파일 목록 | `#bo_v_file ul li a.view_file_download` |
| 첨부파일 다운로드 URL | `download.php?bo_table={board}&wr_id={id}&no={fileIndex}` |
| 이전/다음 글 | `ul.bo_v_nb li a` |

**pharm.skku.edu 추가 셀렉터:**

| 요소 | CSS 셀렉터 |
|------|-----------|
| 제목 | `header h1` |
| 메타 정보 | `header p span.write` (작성자), `span.time` (날짜), `span.hit` (조회수) |
| 첨부파일 | `div.bo_file_layer ul li a` |
| 본문 | `article.new_contents div.contents_wrap #bo_v_con` |

---

## Sub-type C2-custom: GnCommon 커스텀 (nano.skku.edu)

### 대상 사이트

- `https://nano.skku.edu/bbs/board.php?tbl=bbs42` (나노공학과 공지사항)

### 인코딩

- UTF-8 (`<meta http-equiv="Content-Type" content="text/html; charset=utf-8">`)

### 목록 페이지 HTML 구조

GnCommon 솔루션 기반 커스텀 게시판. 그누보드5와 **완전히 다른 구조**.

```html
<div class="conbody">
  <table class="bbs_categ">
    <tr>
      <td>
        <img src="/skin/bbs/basic_responsive/images/btn_notice.gif">  <!-- 공지 아이콘 -->
      </td>
      <td>
        <a href="/bbs/board.php?tbl=bbs42&mode=VIEW&num=416&category=&findType=&findWord=&sort1=&sort2=&it_id=&shop_flag=&mobile_flag=&page=1">
          ★ 나노공학과 2026학년도 1학기 졸업평가 안내
        </a>
      </td>
      <td>2026-03-09</td>                                              <!-- 날짜 -->
      <td>관리자 | 2026-03-09 | 조회수 : 147</td>                      <!-- 메타 정보 -->
    </tr>
  </table>
</div>
```

**주의**: 작성자, 날짜, 조회수가 하나의 `<td>`에 `|`로 구분되어 들어있는 경우가 있다. 파싱 시 텍스트 분할 필요.

**셀렉터:**

| 요소 | CSS 셀렉터 |
|------|-----------|
| 게시글 행 | `div.conbody table tr` (thead 제외) |
| 공지 여부 | `td:first-child img[src*="btn_notice"]` 존재 여부 |
| 제목 + 링크 | `td:nth-child(2) a` |
| 날짜 | `td:nth-child(3)` 또는 메타 td에서 파싱 |
| 메타 정보 | `td:last-child` 텍스트를 `\|`로 split |

### articleNo 추출 패턴

```
href="/bbs/board.php?tbl=bbs42&mode=VIEW&num={articleNo}&..."
```

- 파라미터명: `num`
- 예시: `num=416`, `num=411`
- URL에서 정규식으로 추출: `num=(\d+)`
- **주의**: `tbl` 파라미터 사용 (표준 그누보드의 `bo_table`과 다름)

### 페이지네이션

```
/bbs/board.php?tbl=bbs42&...&page={pageNumber}
```

- 파라미터명: `page`
- 1-based

### 상세 페이지 HTML 구조

```
https://nano.skku.edu/bbs/board.php?tbl=bbs42&mode=VIEW&num=416&...&page=1
```

```html
<div id="sub_contents">
  <div class="inner">
    <div class="conbody">
      <table width="100%">
        <!-- 제목 행 -->
        <tr>
          <td style="padding:10px 20px" colspan="6">
            <strong>★ 나노공학과 2026학년도 1학기 졸업평가 안내</strong>
          </td>
        </tr>

        <!-- 메타 정보 행 -->
        <tr>
          <td colspan="6">
            <ul class="bbs_top clfix">
              <li class="bg_none"><em class="tit">글쓴이</em><span> 관리자</span></li>
              <li><em class="tit">작성일</em><span> 2026-03-09 14:54:22</span></li>
              <li><em class="tit">조회수</em><span> 147</span></li>
            </ul>
          </td>
        </tr>

        <!-- 첨부파일 행 -->
        <tr>
          <td colspan="6">
            <em class="tit">첨부파일</em>
            <span>
              <a href='/bbs/download.php?tbl=bbs42&no=419'>파일명1.hwp</a> |
              <a href='/bbs/download.php?tbl=bbs42&no=420'>파일명2.hwp</a>
            </span>
          </td>
        </tr>

        <!-- 본문 -->
        <tr>
          <td colspan="6">
            <div id="DivContents" style="line-height:1.4;word-break:break-all;">
              <!-- 본문 HTML (HWP 에디터 출력) -->
            </div>
          </td>
        </tr>
      </table>
    </div>
  </div>
</div>
```

**상세 페이지 셀렉터:**

| 요소 | CSS 셀렉터 |
|------|-----------|
| 제목 | `div.conbody table tr:nth-child(1) td strong` |
| 메타 정보 | `ul.bbs_top li` (em.tit 다음 span에서 값 추출) |
| 작성자 | `ul.bbs_top li:nth-child(1) span` |
| 날짜 | `ul.bbs_top li:nth-child(2) span` |
| 조회수 | `ul.bbs_top li:nth-child(3) span` |
| 첨부파일 | 첨부파일 행의 `a[href*="download.php"]` |
| 본문 컨텐츠 | `#DivContents` |

**첨부파일 다운로드 URL:**
```
/bbs/download.php?tbl={boardName}&no={fileNo}
```

---

## 전략 분리 판단

### C1과 C2는 별도 전략이 필수

| 항목 | C1 (cal.skku.edu) | C2-gnuboard | C2-custom (nano) |
|------|-------------------|-------------|------------------|
| URL 구조 | `index.php?hCode=BOARD&bo_idx=N` | `board.php?bo_table=X` | `board.php?tbl=X` |
| 게시글 ID 파라미터 | `idx` | `wr_id` | `num` |
| 페이지 파라미터 | `pg` | `page` | `page` |
| 목록 셀렉터 | `#con_area table tr` | `#bo_list table tr` 또는 `ol.bo_lst li` | `div.conbody table tr` |
| 상세 컨텐츠 | `div.board_content` | `#bo_v_con` | `#DivContents` |
| 전역 JS 변수 | 없음 | `g5_bo_table` 등 | 없음 |

### 권장 전략 구조

```
strategies/
  gnuboard.ts        # C2-gnuboard (bio, pharm 등)
  gnuboard-custom.ts # C2-custom (nano 등 GnCommon 기반)
  custom-php.ts      # C1 (cal 등 자체 PHP)
```

**C2-gnuboard 내부에서는 스킨별 셀렉터 차이를 departments.json의 selectors로 처리.**
bio.skku.edu (테이블형)과 pharm.skku.edu (리스트형)은 같은 전략에서 셀렉터만 다르게 설정.

---

## departments.json 설정 예시

### C1: 커스텀 PHP (custom-php 전략)

```json
{
  "id": "cal-undergrad",
  "name": "건설환경공학부(학부)",
  "strategy": "custom-php",
  "baseUrl": "https://cal.skku.edu/index.php",
  "boardParams": {
    "hCode": "BOARD",
    "bo_idx": "17"
  },
  "selectors": {
    "listRow": "#con_area table tr",
    "titleLink": "td:nth-child(3) a",
    "number": "td:nth-child(1)",
    "category": "td:nth-child(2)",
    "views": "td:nth-child(4)",
    "date": "td:nth-child(5)",
    "detailContent": "div.board_content",
    "detailTitle": "table.board_Vtable thead tr:first-child th",
    "detailMeta": "table.board_Vtable thead tr:nth-child(2) ul li"
  },
  "pagination": {
    "type": "page",
    "param": "pg"
  },
  "articleIdParam": "idx"
}
```

```json
{
  "id": "cal-grad",
  "name": "건설환경공학부(대학원)",
  "strategy": "custom-php",
  "baseUrl": "https://cal.skku.edu/index.php",
  "boardParams": {
    "hCode": "BOARD",
    "bo_idx": "18"
  },
  "selectors": {
    "listRow": "#con_area table tr",
    "titleLink": "td:nth-child(3) a",
    "number": "td:nth-child(1)",
    "category": "td:nth-child(2)",
    "views": "td:nth-child(5)",
    "date": "td:nth-child(6)",
    "detailContent": "div.board_content",
    "detailTitle": "table.board_Vtable thead tr:first-child th",
    "detailMeta": "table.board_Vtable thead tr:nth-child(2) ul li"
  },
  "pagination": {
    "type": "page",
    "param": "pg"
  },
  "articleIdParam": "idx"
}
```

### C2-gnuboard: 표준 그누보드5

```json
{
  "id": "bio-undergrad",
  "name": "생명과학과(학부)",
  "strategy": "gnuboard",
  "baseUrl": "http://bio.skku.edu/bbs/board.php",
  "boardParam": "bo_table",
  "boardName": "N4",
  "selectors": {
    "listRow": "#bo_list .spage table.table tbody tr",
    "titleLink": "td:nth-child(2) a",
    "number": "td:nth-child(1)",
    "author": "td:nth-child(3) .sv_member",
    "views": "td:nth-child(4)",
    "date": "td:nth-child(5)",
    "hasAttachment": "td:nth-child(2) i.fa-download",
    "detailContent": "#bo_v_con",
    "detailTitle": "#bo_v_title .bo_v_tit",
    "detailAttachment": "#bo_v_file ul li a.view_file_download"
  },
  "pagination": {
    "type": "page",
    "param": "page"
  },
  "articleIdParam": "wr_id",
  "encoding": "utf-8"
}
```

```json
{
  "id": "bio-grad",
  "name": "생명과학과(대학원)",
  "strategy": "gnuboard",
  "baseUrl": "http://bio.skku.edu/bbs/board.php",
  "boardParam": "bo_table",
  "boardName": "N5",
  "selectors": {
    "listRow": "#bo_list .spage table.table tbody tr",
    "titleLink": "td:nth-child(2) a",
    "number": "td:nth-child(1)",
    "author": "td:nth-child(3) .sv_member",
    "views": "td:nth-child(4)",
    "date": "td:nth-child(5)",
    "hasAttachment": "td:nth-child(2) i.fa-download",
    "detailContent": "#bo_v_con",
    "detailTitle": "#bo_v_title .bo_v_tit",
    "detailAttachment": "#bo_v_file ul li a.view_file_download"
  },
  "pagination": {
    "type": "page",
    "param": "page"
  },
  "articleIdParam": "wr_id",
  "encoding": "utf-8"
}
```

```json
{
  "id": "pharm",
  "name": "약학대학",
  "strategy": "gnuboard",
  "baseUrl": "https://pharm.skku.edu/bbs/board.php",
  "boardParam": "bo_table",
  "boardName": "notice",
  "selectors": {
    "listItem": "ol.bo_lst > li",
    "titleLink": "li > a",
    "titleText": "article.bo_info h2",
    "category": "span.category",
    "author": "span.write",
    "date": "span.time",
    "hasAttachment": "span.lst_file",
    "detailContent": "#bo_v_con",
    "detailTitle": "header h1",
    "detailMeta": "header p",
    "detailAttachment": "div.bo_file_layer ul li a"
  },
  "pagination": {
    "type": "page",
    "param": "page"
  },
  "articleIdParam": "wr_id",
  "encoding": "utf-8"
}
```

### C2-custom: GnCommon 커스텀

```json
{
  "id": "nano",
  "name": "나노공학과",
  "strategy": "gnuboard-custom",
  "baseUrl": "https://nano.skku.edu/bbs/board.php",
  "boardParam": "tbl",
  "boardName": "bbs42",
  "selectors": {
    "listRow": "div.conbody table tr",
    "titleLink": "td:nth-child(2) a",
    "isNotice": "td:first-child img[src*='btn_notice']",
    "date": "td:nth-child(3)",
    "meta": "td:nth-child(4)",
    "detailContent": "#DivContents",
    "detailTitle": "div.conbody table tr:nth-child(1) td strong",
    "detailMeta": "ul.bbs_top li",
    "detailAttachment": "a[href*='download.php']"
  },
  "pagination": {
    "type": "page",
    "param": "page"
  },
  "articleIdParam": "num",
  "detailMode": "VIEW",
  "encoding": "utf-8"
}
```

---

## 구현 시 주의사항

### 1. 날짜 파싱

| 사이트 | 목록 날짜 형식 | 상세 날짜 형식 |
|--------|-------------|-------------|
| cal.skku.edu | `YYYY-MM-DD` | `YYYY-MM-DD HH:mm:ss` |
| bio.skku.edu | `MM-DD` (연도 없음!) | `YY-MM-DD HH:mm` |
| pharm.skku.edu | `YYYY-MM-DD` | `YY-MM-DD` |
| nano.skku.edu | `YYYY-MM-DD` | `YYYY-MM-DD HH:mm:ss` |

- bio.skku.edu 목록의 `MM-DD`는 연도 추정 필요 (현재 연도 기준, 12월 글이 1월에 조회되면 전년도)
- `YY-MM-DD` 형식은 `20` prefix 추가 필요

### 2. URL 정규화

- pharm.skku.edu의 href가 `//pharm.skku.edu/...` (프로토콜 상대) → `https:` 붙이기
- bio.skku.edu는 절대 URL (`http://bio.skku.edu/...`) → HTTP 그대로 사용 (HTTPS 미지원 가능)
- cal.skku.edu는 상대 URL (`?page=view&...`) → baseUrl + 상대경로

### 3. 공지글 필터링

- C1: 첫 번째 td가 "공지" 텍스트
- C2 bio: 별도 공지 마크 미확인 (번호가 표시됨)
- C2 pharm: `span.category` 텍스트가 "공지"
- C2 nano: `img[src*="btn_notice"]` 존재

### 4. 첨부파일 다운로드 URL

| 사이트 | 다운로드 URL 패턴 |
|--------|-----------------|
| bio.skku.edu | `/bbs/download.php?bo_table={board}&wr_id={id}&no={fileIndex}` |
| pharm.skku.edu | `/bbs/download.php?bo_table={board}&wr_id={id}&no={fileIndex}` |
| nano.skku.edu | `/bbs/download.php?tbl={board}&no={fileNo}` |
| cal.skku.edu | 별도 첨부파일 URL 미확인 |

### 5. HTTP vs HTTPS

| 사이트 | 프로토콜 |
|--------|---------|
| cal.skku.edu | HTTPS |
| bio.skku.edu | HTTP (HTTPS 미지원 가능) |
| pharm.skku.edu | HTTPS |
| nano.skku.edu | HTTPS |

### 6. HWP 에디터 본문

nano.skku.edu 상세 페이지의 `#DivContents` 내부에는 HWP(한글) 에디터에서 생성된 HTML이 포함된다.
`data-hwpjson` 속성의 JSON 데이터가 매우 길 수 있으며 (`data-jsonlen="34189"`), 본문 파싱 시 이 JSON을 제거해야 한다.
`div#hwpEditorBoardContent` 내부의 `<!--[data-hwpjson]...[data-hwpjson]-->` 주석도 제거 대상.

### 7. 스킨 감지 로직

같은 gnuboard 전략이라도 스킨에 따라 셀렉터가 달라진다. 자동 감지가 필요하면:

1. `g5_bo_table` JS 변수 존재 → 그누보드5 확인
2. `ol.bo_lst#board_list` 존재 → 리스트형 스킨
3. `#bo_list table` 존재 → 테이블형 스킨
4. `div.conbody table` + `tbl=` 파라미터 → GnCommon 커스텀

하지만 **departments.json에서 명시적으로 셀렉터를 지정하는 것이 더 안정적**이다.
