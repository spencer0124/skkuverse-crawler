# ASP 게시판 크롤링 전략 (Type E)

## 사이트 개요

| 항목 | 값 |
|------|-----|
| 대상 | 성균관대학교 의과대학 공지사항 |
| 도메인 | `www.skkumed.ac.kr` (skku.edu가 아님 -- 별도 도메인) |
| 기술 스택 | Classic ASP + EUC-KR |
| 목록 URL | `https://www.skkumed.ac.kr/community_notice.asp` |
| 상세 URL | `https://www.skkumed.ac.kr/community_notice_w.asp?bcode=nt&number={articleNo}&pg={page}` |
| 페이지당 항목 수 | 20 |
| 에디터 | DEXT5 (Raon) — 본문이 `<head><body>` 포함한 HTML fragment로 삽입됨 |

### skku-standard와의 비교

ASP 사이트는 skku.edu 표준 게시판과 CSS 클래스명이 **거의 동일**하지만, 다음 차이가 있다:

| 구분 | skku-standard | ASP (skkumed) |
|------|---------------|---------------|
| 인코딩 | UTF-8 | **EUC-KR** |
| articleNo 추출 | `?mode=view&articleNo=N` | `community_notice_w.asp?bcode=nt&number=N` |
| 카테고리 | `span.c-board-list-category` 존재 | 카테고리 **없음** |
| 페이지네이션 | offset 방식 (`article.offset=N`) | **pageNum 방식** (`pg=N`) |
| 상세 본문 셀렉터 | `dl.board-write-box dd` | `div.board-view-content-wrap div.fr-view` |
| 첨부파일 목록 | `ul.filedown_list li a` | `ul.board-view-file-wrap li a` |
| 첨부파일 다운로드 | `?mode=download&articleNo=N&attachNo=M` | `download_board_file.asp?bcode=nt&number=N&fileidx=M` |
| NEW 표시 | `span.c-board-list-new` | 없음 |

## 목록 페이지 HTML 구조

### 전체 컨테이너

```html
<div class="common common-board">
  <form id="searchForm" method="post" action="/community_notice.asp">
    <!-- 검색 폼 -->
  </form>
  <div class="board-name-list board-wrap">
    <ul class="board-list-wrap">
      <li class=" ">...</li>  <!-- 개별 공지 항목 -->
      <li class=" ">...</li>
      <!-- 20개 반복 -->
    </ul>
  </div>
  <ul class="paging-wrap">...</ul>
</div>
```

### 개별 항목 구조

```html
<li class=" ">
  <dl class="board-list-content-wrap ">
    <dt class="board-list-content-title ">
      ·
      <a href="community_notice_w.asp?bcode=nt&number=4665&pg=1" title="자세히 보기">
        Elsevier 학습관리 플랫폼( Osmosis) 1차 사용 설명회 개최
      </a>
    </dt>
    <dd class="board-list-content-info">
      <ul>
        <li>&nbsp;&nbsp;&nbsp;No.4665 </li>   <!-- [0] 순번 -->
        <li>의학교육학교실</li>                   <!-- [1] 작성자/부서 -->
        <li>2026-03-20</li>                     <!-- [2] 날짜 -->
        <li>조회수 <span class="board-mg-l10">315</span></li>  <!-- [3] 조회수 -->
      </ul>
    </dd>
  </dl>

  <!-- 첨부파일이 있는 경우에만 존재 -->
  <div class="board-list-etc-wrap">
    <ul>
      <a href="community_notice_w.asp?bcode=nt&number=4665&pg=1" title="자세히 보기">
        <li class="c-board-file-icon board-list-file">
          <span class="hide">첨부파일</span>
        </li>
      </a>
    </ul>
  </div>
</li>
```

### CSS 셀렉터 매핑 (목록)

| 용도 | 셀렉터 |
|------|--------|
| 항목 컨테이너 | `dl.board-list-content-wrap` |
| 제목 링크 | `dt.board-list-content-title a` |
| 메타 정보 리스트 | `dd.board-list-content-info ul li` |
| 첨부파일 아이콘 | `li.c-board-file-icon` (있으면 첨부파일 존재) |

### articleNo 추출

href 패턴: `community_notice_w.asp?bcode=nt&number=4665&pg=1`

```typescript
const match = href.match(/number=(\d+)/);
const articleNo = match ? parseInt(match[1], 10) : null;
```

> **주의**: skku-standard는 `articleNo=(\d+)` 패턴이지만, ASP는 `number=(\d+)` 패턴이다.

### 메타 정보 파싱

`dd.board-list-content-info ul li` 의 순서:

| 인덱스 | 내용 | 예시 | 파싱 |
|--------|------|------|------|
| 0 | 순번 | `No.4665` | `/No\.(\d+)/` (참고용, articleNo와 동일) |
| 1 | 작성자/부서 | `의학교육학교실` | `.trim()` |
| 2 | 날짜 | `2026-03-20` | 그대로 사용 (YYYY-MM-DD) |
| 3 | 조회수 | `조회수 315` | `/(\d+)/` |

## 상세 페이지 HTML 구조

### URL 패턴

```
https://www.skkumed.ac.kr/community_notice_w.asp?bcode=nt&number={articleNo}&pg={page}
```

- `bcode=nt` — 게시판 코드 (notice)
- `number` — 글 번호 (articleNo)
- `pg` — 현재 페이지 (목록으로 돌아갈 때 사용, 크롤링에서는 생략 가능)

### HTML 구조

```html
<div class="content" id="jwxe_main_content">
  <div class="content-box">
    <div class="board-name-view board-wrap">
      <div class="board-view-box ">

        <!-- 제목 + 메타 -->
        <div class="board-view-title-wrap">
          <h4>게시글 제목</h4>
          <ul class="board-etc-wrap">
            <li>의학교육학교실</li>                          <!-- 작성자 -->
            <li>조회수 <span class="board-mg-l10">315</span></li>  <!-- 조회수 -->
            <li>2026-03-20 오전 10:59:26</li>               <!-- 날짜+시간 -->
          </ul>
        </div>

        <!-- 첨부파일 (있는 경우에만) -->
        <ul class="board-view-file-wrap">
          <li>
            <a class="file-down-btn pptx"
               href="download_board_file.asp?bcode=nt&number=4665&fileidx=6045">
              Elsevier 설명회 포스터_1.jpg
            </a>
          </li>
          <!-- 여러 파일 가능 -->
        </ul>

        <!-- 본문 -->
        <div class="board-view-content-wrap board-view-txt">
          <div class="fr-view">
            <p>
              <head>...</head>      <!-- DEXT5 에디터가 삽입한 head -->
              <body id="dext_body">
                <!-- 실제 본문 HTML -->
              </body>
            </p>
          </div>
        </div>

      </div>
    </div>

    <!-- 이전글/다음글 -->
    <div class="board-txt-navi-wrap">
      <dl class="board-txt-navi-box">
        <dt>이전글</dt>
        <dd><a href="community_notice_w.asp?bcode=nt&number=4664">이전 제목</a></dd>
      </dl>
      <dl class="board-txt-navi-box">
        <dt>다음글</dt>
        <dd><a href="community_notice_w.asp?bcode=nt&number=4666">다음 제목</a></dd>
      </dl>
    </div>
  </div>
</div>
```

### CSS 셀렉터 매핑 (상세)

| 용도 | 셀렉터 |
|------|--------|
| 제목 | `div.board-view-title-wrap h4` |
| 메타 정보 | `ul.board-etc-wrap li` |
| 첨부파일 목록 | `ul.board-view-file-wrap li a` |
| 본문 컨테이너 | `div.board-view-content-wrap div.fr-view` |
| 이전글/다음글 | `div.board-txt-navi-wrap dl.board-txt-navi-box` |

### 첨부파일 다운로드 URL

```
download_board_file.asp?bcode=nt&number={articleNo}&fileidx={fileIdx}
```

- 상대 경로 → `https://www.skkumed.ac.kr/` 를 baseUrl로 붙여서 절대 경로 생성
- `a` 태그의 class에 파일 확장자 힌트 포함 (예: `file-down-btn pptx`)
- 파일명은 `a` 태그의 text content

### 본문 파싱 주의사항

DEXT5 (Raon) 에디터가 생성한 본문은 `<head><body>` 를 포함하는 HTML fragment다:

```html
<div class="fr-view">
  <p>
    <head><title>제목없음</title><style>...</style></head>
    <body id="dext_body" spellcheck="false">
      <!-- 실제 본문 -->
    </body>
  </p>
</div>
```

cheerio가 이를 파싱할 때 `<head>` 는 무시되고 `<body>` 내용이 DOM에 포함된다. 파싱 시:

```typescript
// 방법 1: fr-view 전체를 가져온 후 style 태그 제거
const $content = $('div.board-view-content-wrap div.fr-view');
$content.find('style').remove();
$content.find('head').remove();
const content = $content.html()?.trim() || '';

// 방법 2: body#dext_body가 있으면 그 내부만 추출
const $body = $content.find('body#dext_body');
const content = $body.length ? $body.html()?.trim() : $content.html()?.trim() || '';
```

## 페이지네이션

### 방식: pageNum (페이지 번호)

URL 패턴:
```
/community_notice.asp?keyword=&startpage={group}&bcode=nt&pg={page}
```

| 파라미터 | 설명 | 예시 |
|----------|------|------|
| `pg` | 현재 페이지 번호 (1부터 시작) | `pg=1`, `pg=2`, ... |
| `startpage` | 페이지 그룹 시작 번호 | 1~10 → `startpage=1`, 11~20 → `startpage=11` |
| `bcode` | 게시판 코드 | `nt` (notice) |
| `keyword` | 검색어 | 빈 문자열 (크롤링 시 불필요) |

### 페이지네이션 HTML

```html
<ul class="paging-wrap">
  <!-- 이전 그룹 (첫 그룹이 아닌 경우) -->
  <a HREF="/community_notice.asp?keyword=&bcode=nt&pg=10&startpage=10">이전</a>

  <!-- 현재 페이지: <b> 태그 (링크 없음) -->
  <b>11</b>

  <!-- 다른 페이지: <li><a> -->
  <li><a class="active" HREF="/community_notice.asp?keyword=&startpage=11&bcode=nt&pg=12">12</a></li>
  <li><a class="active" HREF="/community_notice.asp?keyword=&startpage=11&bcode=nt&pg=13">13</a></li>
  <!-- ... 10개 단위 -->

  <!-- 다음 그룹 -->
  <a HREF="/community_notice.asp?keyword=&bcode=nt&pg=12&startpage=11">다음</a>
</ul>
```

### 크롤링 시 페이지네이션 처리

`startpage`는 UI 그룹 표시용일 뿐, **크롤링에서는 `pg` 파라미터만 증가**시키면 된다:

```typescript
// 1페이지: pg=1
// 2페이지: pg=2
// N페이지: pg=N
const url = `${baseUrl}?bcode=nt&pg=${page}`;
```

`startpage`는 생략해도 서버가 정상 응답한다.

### 마지막 페이지 감지

- `dl.board-list-content-wrap` 이 0개이면 → 더 이상 글 없음 (마지막 페이지 초과)
- incremental crawl에서는 1페이지의 모든 articleNo가 DB에 있으면 early stop

## 인코딩 처리 (EUC-KR)

### 문제

```html
<meta http-equiv="Content-Type" content="text/html; charset=euc-kr" />
```

이 사이트는 **EUC-KR** 인코딩을 사용한다. axios의 기본 `responseType: 'text'`는 UTF-8을 가정하므로, EUC-KR 페이지를 fetch하면 한글이 깨진다.

### 해결: iconv-lite

```bash
npm install iconv-lite
```

```typescript
import iconv from 'iconv-lite';

// Fetcher에서 arraybuffer로 받아서 EUC-KR → UTF-8 변환
const response = await axios.get(url, {
  responseType: 'arraybuffer',
  timeout: 10000,
});
const html = iconv.decode(Buffer.from(response.data), 'euc-kr');
```

### 전략별 인코딩 설정

departments.json에 `encoding` 필드를 추가하여 전략에서 분기:

```json
{
  "encoding": "euc-kr"
}
```

Fetcher 또는 Strategy에서:
```typescript
if (config.encoding === 'euc-kr') {
  const response = await axios.get(url, { responseType: 'arraybuffer' });
  return iconv.decode(Buffer.from(response.data), 'euc-kr');
} else {
  const response = await axios.get(url, { responseType: 'text' });
  return response.data;
}
```

## departments.json 설정 예시

```json
{
  "id": "medicine",
  "name": "의과대학",
  "strategy": "skkumed-asp",
  "baseUrl": "https://www.skkumed.ac.kr/community_notice.asp",
  "detailBaseUrl": "https://www.skkumed.ac.kr/community_notice_w.asp",
  "encoding": "euc-kr",
  "selectors": {
    "listItem": "dl.board-list-content-wrap",
    "titleLink": "dt.board-list-content-title a",
    "infoList": "dd.board-list-content-info ul li",
    "detailContent": "div.board-view-content-wrap div.fr-view",
    "attachmentList": "ul.board-view-file-wrap li a"
  },
  "pagination": {
    "type": "pageNum",
    "param": "pg",
    "limit": 20
  },
  "extraParams": {
    "bcode": "nt"
  }
}
```

### 설정 필드 설명

| 필드 | 설명 |
|------|------|
| `strategy` | `skkumed-asp` — ASP 전용 전략 |
| `baseUrl` | 목록 페이지 URL |
| `detailBaseUrl` | 상세 페이지 URL 베이스 (목록과 다름!) |
| `encoding` | `euc-kr` — Fetcher에서 arraybuffer + iconv 변환 |
| `extraParams.bcode` | 게시판 코드 (`nt` = notice) |
| `pagination.type` | `pageNum` — 페이지 번호 방식 (1부터 시작) |
| `pagination.limit` | 20 — 페이지당 항목 수 |

## 구현 체크리스트

### Fetcher 변경

- [ ] `encoding` 옵션 지원: `euc-kr`이면 `responseType: 'arraybuffer'` + `iconv.decode()`
- [ ] `iconv-lite` 패키지 추가

### 새 Strategy: `skkumed-asp.ts`

- [ ] `crawlList()` 구현
  - URL 조합: `${baseUrl}?bcode=${bcode}&pg=${page}`
  - `number=(\d+)` 패턴으로 articleNo 추출
  - 카테고리 필드 없음 (빈 문자열)
  - infoList 파싱 (순번, 작성자, 날짜, 조회수)
  - detailPath: href 그대로 저장 (`community_notice_w.asp?bcode=nt&number=N&pg=P`)

- [ ] `crawlDetail()` 구현
  - URL 조합: `https://www.skkumed.ac.kr/${detailPath}` (상대 경로 → 절대 경로)
  - 본문: `div.board-view-content-wrap div.fr-view` → style/head 제거 후 html 추출
  - 첨부파일: `ul.board-view-file-wrap li a` → href + text
  - 첨부 URL: `download_board_file.asp?...` → origin 붙여서 절대 경로

### types.ts 변경

- [ ] `SkkumedAspDepartmentConfig` 인터페이스 추가
  - `encoding?: string` 필드
  - `detailBaseUrl?: string` 필드
- [ ] `DepartmentConfig` 유니온에 추가
- [ ] `PageNumPaginationConfig` (이미 존재) 사용

### Config Validation

- [ ] `skkumed-asp` 전략 필수 셀렉터: `listItem`, `titleLink`, `infoList`, `detailContent`, `attachmentList`
- [ ] `encoding` 필드 검증 (허용값: `utf-8`, `euc-kr`)

## 참고: 같은 ASP 사이트의 다른 게시판

skkumed.ac.kr에는 공지사항 외에도 여러 게시판이 같은 ASP 구조를 사용할 가능성이 있다:
- `bcode=nt` → 공지사항
- 다른 `bcode` 값이 있을 수 있음

향후 같은 도메인의 다른 게시판을 추가할 때는 `extraParams.bcode`만 변경하면 된다.
