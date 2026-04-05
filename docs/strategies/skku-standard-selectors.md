# skku-standard 게시판 구조

## 타겟 사이트

`www.skku.edu` 기반 표준 게시판. 본교 공지, 대부분의 학과 공지에서 사용.

## 목록 페이지 HTML 구조

```html
<li>
  <dl class="board-list-content-wrap">
    <dt class="board-list-content-title">
      <span class="c-board-list-category">[행사/세미나]</span>
      <a href="?mode=view&articleNo=135890&article.offset=0&articleLimit=10">
        게시글 제목
      </a>
      <span class="c-board-list-new">NEW</span>  <!-- 새 글 표시 (선택적) -->
    </dt>
    <dd class="board-list-content-info">
      <ul>
        <li>No.24662</li>       <!-- 순번 (articleNo와 다름) -->
        <li>김선영</li>          <!-- 작성자 -->
        <li>2026-03-27</li>     <!-- 날짜 -->
        <li>조회수<span class="board-mg-l10">592</span></li>
      </ul>
    </dd>
  </dl>
  <div class="board-list-etc-wrap">
    <ul>
      <li class="c-board-file-icon board-list-file">  <!-- 첨부파일 아이콘 (선택적) -->
        <span class="hide">첨부파일</span>
      </li>
    </ul>
  </div>
</li>
```

## 상세 페이지 HTML 구조

```html
<table class="board_view">
  <thead>
    <tr>
      <th>
        <span class="category">[행사/세미나]</span>
        <em class="ellipsis">게시글 제목</em>
        <span class="date">최종 수정일 : 2026.03.27</span>
      </th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>
        <!-- 메타 정보 영역 -->
        <div class="boardView_txtWrap">...</div>

        <!-- 본문 -->
        <dl class="board-write-box board-write-box-v03">
          <dt class="hide">게시글 내용</dt>
          <dd>
            <pre class="pre">본문 텍스트...</pre>
            <!-- 또는 HTML 본문 -->
          </dd>
        </dl>
      </td>
    </tr>
  </tbody>
</table>
```

## 첨부파일 HTML 구조

```html
<div class="file_downWrap">
  <ul class="filedown_list">
    <li>
      <a class="ellipsis" href="?mode=download&articleNo=135875&attachNo=113130">
        파일명.pdf
      </a>
    </li>
  </ul>
  <ul class="filedown_btnList">
    <li><button>전체다운로드</button></li>
  </ul>
</div>
```

- 다운로드 URL은 상대 경로 (`?mode=download&...`) → baseUrl에 붙여서 절대 경로로 변환
- `href="#"` 인 UI 토글 링크는 필터링

## 페이지네이션

- URL: `?mode=list&articleLimit=10&article.offset=N`
- N = page × 10 (0, 10, 20, ...)
- 빈 리스트가 나오면 마지막 페이지

## departments.json 셀렉터 매핑

```json
{
  "listItem": "dl.board-list-content-wrap",
  "category": "span.c-board-list-category",
  "titleLink": "dt.board-list-content-title a",
  "infoList": "dd.board-list-content-info ul li",
  "detailContent": "dl.board-write-box dd",
  "attachmentList": "ul.filedown_list li a"
}
```

### 학과별 차이 가능성

같은 skku-standard 전략이지만 학과별로 셀렉터가 다를 수 있음:
- `infoList`의 `<li>` 순서가 다를 수 있음 (작성자/날짜 위치)
- `detailContent`의 클래스가 다를 수 있음
- departments.json에서 selectors를 학과별로 오버라이드 가능
