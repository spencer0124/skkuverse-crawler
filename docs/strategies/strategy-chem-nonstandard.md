# 화학과 비표준 게시판 구조 분석

## 개요

**타겟**: https://chem.skku.edu/chem/News/notice.do (화학과 공지사항)

화학과 게시판은 SKKU CMS(`.do` URL) 위에서 동작하지만, 표준 SKKU 게시판(`dl.board-list-content-wrap`)과 **완전히 다른 HTML 템플릿**을 사용한다. URL 패턴, 페이지네이션, articleNo 체계는 동일하지만 DOM 구조가 다르다.

### 왜 다른가?

- **게시판 타입**: `boardTy = 'chem_common'` (표준은 `common` 또는 `custom`)
- **커스텀 리소스**: `/_custom/shb/resource/` 경로의 CSS/JS 사용
- **보드 템플릿**: `/_res/board_new/` + `/_res/chem/` 조합 (표준은 `/_res/board/` 단일)
- **에디터**: Froala Editor 기반 (`editorVendor = 'froala'`)
- **사이트 ID**: `_siteId = 'chem'` (독립 사이트 설정)

핵심: 같은 SKKU CMS 플랫폼이지만 **학과 자체 커스텀 보드 스킨**을 사용하여 HTML 구조가 다르다. `ul/li/h3` 패턴 vs 표준 `dl/dt/dd` 패턴.

---

## 목록 페이지 HTML 구조

### 표준 SKKU (비교용)

```html
<li>
  <dl class="board-list-content-wrap">
    <dt class="board-list-content-title">
      <span class="c-board-list-category">[행사/세미나]</span>
      <a href="?mode=view&articleNo=135890&article.offset=0&articleLimit=10">제목</a>
    </dt>
    <dd class="board-list-content-info">
      <ul>
        <li>No.24662</li>
        <li>김선영</li>
        <li>2026-03-27</li>
        <li>조회수<span>592</span></li>
      </ul>
    </dd>
  </dl>
</li>
```

### 화학과 (비표준)

```html
<div class="noticeListWrap">
  <ul class="noticeList">
    <li class="">
      <h3 class="noticeTit ">
        <a href="?mode=view&amp;articleNo=214922&amp;article.offset=0&amp;articleLimit=10"
           title="자세히 보기">
          [학부/대학원] 2026학년도 2학기 新대학원우수장학금 선발 안내
        </a>
      </h3>
      <p class="noticeDesc">
        <a href="?mode=view&amp;articleNo=214922&amp;article.offset=0&amp;articleLimit=10"
           title="자세히 보기">
          ※ 본 장학제도는 2026학년도 후기... (본문 미리보기)
        </a>
      </p>
      <ul class="noticeInfoList">
        <li>POSTED DATE : 2026-03-20</li>
        <li>WRITER : 화학과</li>
        <li>HIT : 280</li>
      </ul>
    </li>
    <!-- ... 반복 -->
  </ul>
</div>
```

### 구조 비교표

| 요소 | 표준 SKKU | 화학과 |
|------|-----------|--------|
| 목록 컨테이너 | (없음, `<li>` 직접) | `ul.noticeList` |
| 개별 항목 | `dl.board-list-content-wrap` | `ul.noticeList > li` |
| 제목 영역 | `dt.board-list-content-title` | `h3.noticeTit` |
| 제목 링크 | `dt.board-list-content-title a` | `h3.noticeTit a` |
| 카테고리 | `span.c-board-list-category` | (없음 - 제목에 [학부/대학원] 등 포함) |
| 메타 정보 | `dd.board-list-content-info ul li` | `ul.noticeInfoList li` |
| 본문 미리보기 | (없음) | `p.noticeDesc` |
| href 패턴 | `?mode=view&articleNo=N&...` | `?mode=view&articleNo=N&...` (동일) |

### 메타 정보 (infoList) 차이

| 인덱스 | 표준 SKKU | 화학과 |
|--------|-----------|--------|
| [0] | `No.24662` (순번) | `POSTED DATE : 2026-03-20` (날짜) |
| [1] | `김선영` (작성자) | `WRITER : 화학과` (작성자) |
| [2] | `2026-03-27` (날짜) | `HIT : 280` (조회수) |
| [3] | `조회수 592` (조회수) | (없음) |

**주의**: 순서가 다르고, 라벨이 포함되어 있다 (`POSTED DATE :`, `WRITER :`, `HIT :`).
표준은 4개 항목이지만 화학과는 3개 항목이며, 순번(No.)이 없다.

### 메타 파싱 로직

```typescript
// 표준: 위치 기반 파싱 (인덱스 의존)
const author = infoTexts[1];      // 두 번째 li
const date = infoTexts[2];        // 세 번째 li
const views = infoTexts[3];       // 네 번째 li에서 숫자 추출

// 화학과: 라벨 기반 파싱 필요
// "POSTED DATE : 2026-03-20" → date = "2026-03-20"
// "WRITER : 화학과" → author = "화학과"
// "HIT : 280" → views = 280
```

---

## 상세 페이지 HTML 구조

### 표준 SKKU (비교용)

```html
<dl class="board-write-box board-write-box-v03">
  <dt class="hide">게시글 내용</dt>
  <dd>
    <pre class="pre">본문 텍스트...</pre>
  </dd>
</dl>

<!-- 첨부파일 -->
<ul class="filedown_list">
  <li>
    <a class="ellipsis" href="?mode=download&articleNo=135875&attachNo=113130">
      파일명.pdf
    </a>
  </li>
</ul>
```

### 화학과 (비표준)

```html
<div class="en board view">
  <div class="noticeViewWrap">
    <input type="hidden" name="articleNo" value="214527"/>

    <div class="noticeViewWrap ">
      <!-- 헤더: 제목 + 메타 -->
      <div class="noticeViewHead ">
        <h3 class="noticeTit ">
          [학부] 2026-1 대학원 한마당 화학과 간담회 및 오픈랩 안내
        </h3>
        <ul class="noticeInfoList">
          <li>POSTED DATE : 2026-03-13</li>
          <li>WRITER : 화학과</li>
          <li>HIT : 308</li>
        </ul>
      </div>

      <!-- 본문 콘텐츠 -->
      <div class="noticeViewCont ">
        <div class="fr-view">
          <p>본문 HTML 내용...</p>
          <img src="/_res/editor_image/2026/03/xxxxx.jpg" ...>
        </div>
      </div>

      <!-- 첨부파일 -->
      <div class="noticeViewBtnWrap">
        <div class="noticeViewBtnList">
          <button class="fileBtn fileBtnBlue"
                  onclick="location.href='?mode=download&amp;articleNo=214922&amp;attachNo=187134'">
            파일명.hwp
          </button>
          <!-- 반복 -->
        </div>
        <button class="allDownBtn"
                onclick="location.href='/app/board/downloadZip.do?articleNo=214922'">
          전체다운로드
        </button>
      </div>
    </div>

    <!-- 이전글/다음글 -->
    <ul class="viewNextPrev">
      <li>
        <a href="?mode=view&amp;articleNo=214537&...">NEXT</a>
        <a href="..." class="viewBtmTit">다음글 제목</a>
      </li>
      <li>
        <a href="?mode=view&amp;articleNo=214436&...">PREV</a>
        <a href="..." class="viewBtmTit">이전글 제목</a>
      </li>
    </ul>
  </div>
</div>
```

### 상세 페이지 비교표

| 요소 | 표준 SKKU | 화학과 |
|------|-----------|--------|
| 본문 컨테이너 | `dl.board-write-box dd` | `div.noticeViewCont` |
| 본문 내부 | `<pre class="pre">` 또는 HTML | `div.fr-view` (Froala 에디터 출력) |
| 첨부파일 목록 | `ul.filedown_list li a` | `div.noticeViewBtnList button.fileBtn` |
| 첨부 링크 방식 | `<a href="?mode=download&...">` | `<button onclick="location.href='?mode=download&...'">` |
| 전체다운로드 | `<button>` (filedown_btnList) | `button.allDownBtn` |

### 첨부파일 파싱 차이

```typescript
// 표준: <a> 태그의 href 속성
$(config.selectors.attachmentList).each((_, el) => {
  const name = $(el).text().trim();
  const url = $(el).attr('href');
});

// 화학과: <button>의 onclick 속성에서 URL 추출 필요
$('div.noticeViewBtnList button.fileBtn').each((_, el) => {
  const name = $(el).text().trim();
  const onclick = $(el).attr('onclick') || '';
  const match = onclick.match(/location\.href='([^']+)'/);
  const url = match ? match[1] : '';
});
```

---

## 페이지네이션

화학과와 표준 SKKU의 페이지네이션은 **완전히 동일**하다.

```
목록: ?mode=list&articleLimit=10&article.offset=N
상세: ?mode=view&articleNo=N&article.offset=0&articleLimit=10
다운: ?mode=download&articleNo=N&attachNo=M
```

- offset = page * 10 (0, 10, 20, ...)
- 페이지당 10개 항목
- `article.offset` 파라미터 사용
- 마지막 페이지: offset=1250 (약 126페이지, 1260+ 개 공지)

페이지네이션 HTML:

```html
<div class="pagingWrap">
  <ul class="paging-wrap">
    <li><a href="#curPage" class="active">1</a></li>
    <li><a href="?mode=list&&articleLimit=10&article.offset=10">2</a></li>
    <!-- ... -->
    <li class="boardNext"><a href="?mode=list&&articleLimit=10&article.offset=10">다음</a></li>
    <li class="boardLast"><a href="?mode=list&&articleLimit=10&article.offset=1250">마지막</a></li>
  </ul>
</div>
```

---

## 구현 방안 분석

### 방안 1: skku-standard 전략에 커스텀 셀렉터만 적용

departments.json에서 셀렉터를 오버라이드하는 방식:

```json
{
  "id": "chem",
  "name": "화학과",
  "strategy": "skku-standard",
  "baseUrl": "https://chem.skku.edu/chem/News/notice.do",
  "selectors": {
    "listItem": "ul.noticeList > li",
    "category": "",
    "titleLink": "h3.noticeTit a",
    "infoList": "ul.noticeInfoList li",
    "detailContent": "div.noticeViewCont",
    "attachmentList": "div.noticeViewBtnList button.fileBtn"
  },
  "pagination": {
    "type": "offset",
    "param": "article.offset",
    "limit": 10
  }
}
```

**문제점**:

1. **infoList 파싱 로직 불일치**: 표준 전략은 `infoTexts[1]` = 작성자, `infoTexts[2]` = 날짜, `infoTexts[3]` = 조회수로 인덱스 기반 파싱한다. 화학과는 `[0]` = 날짜(라벨 포함), `[1]` = 작성자(라벨 포함), `[2]` = 조회수(라벨 포함)로 순서와 형식이 다르다. **라벨 제거 + 인덱스 매핑이 필요.**

2. **첨부파일 파싱 불일치**: 표준은 `<a>` 태그의 `href` 속성을 읽지만, 화학과는 `<button>` 태그의 `onclick` 속성에서 URL을 추출해야 한다. `extractAttr($a, 'href')` → 실패.

3. **카테고리 없음**: `category` 셀렉터가 빈 문자열이면 현재 코드에서 문제없이 동작하지만, 제목에 `[학부/대학원]` 같은 접두사가 포함되어 있어 별도 추출이 가능하긴 하다.

**결론**: 셀렉터만 바꿔서는 **동작하지 않는다**. infoList 파싱과 첨부파일 파싱 로직이 근본적으로 다르다.

### 방안 2: skku-standard 전략을 확장하여 파싱 옵션 추가 (권장)

새로운 전략을 만들지 않고, 기존 `skku-standard` 전략에 **옵션 기반 분기**를 추가:

```typescript
// types.ts 확장
export interface SkkuStandardDepartmentConfig extends BaseDepartmentConfig {
  strategy: 'skku-standard';
  selectors: {
    listItem: string;
    category: string;
    titleLink: string;
    infoList: string;
    detailContent: string;
    attachmentList: string;
  };
  pagination: OffsetPaginationConfig;

  // 새로 추가
  infoParser?: 'standard' | 'labeled';
  attachmentParser?: 'href' | 'onclick';
}
```

```json
{
  "id": "chem",
  "name": "화학과",
  "strategy": "skku-standard",
  "baseUrl": "https://chem.skku.edu/chem/News/notice.do",
  "selectors": {
    "listItem": "ul.noticeList > li",
    "category": "",
    "titleLink": "h3.noticeTit a",
    "infoList": "ul.noticeInfoList li",
    "detailContent": "div.noticeViewCont",
    "attachmentList": "div.noticeViewBtnList button.fileBtn"
  },
  "infoParser": "labeled",
  "attachmentParser": "onclick",
  "pagination": {
    "type": "offset",
    "param": "article.offset",
    "limit": 10
  }
}
```

**장점**:
- 새 전략 파일 불필요
- 같은 SKKU CMS 위의 변형이므로 논리적으로 같은 전략에 속함
- URL/페이지네이션/articleNo 추출 등 대부분의 로직이 동일

**변경 범위**:
- `types.ts`: `infoParser`, `attachmentParser` 옵션 필드 추가
- `skku-standard.ts`: `crawlList()` 내 infoTexts 파싱 분기, `crawlDetail()` 내 첨부파일 파싱 분기

### 방안 3: 별도 전략 (`skku-chem`) 생성

```typescript
// strategies/skku-chem.ts
export class SkkuChemStrategy implements CrawlStrategy { ... }
```

**단점**: URL 패턴, 페이지네이션, articleNo 추출 등 90%의 코드가 `skku-standard`와 중복된다. 유지보수 비용이 커진다.

---

## 권장 구현: 방안 2 (skku-standard 확장)

### 변경 파일

1. **`src/common/types.ts`** — `SkkuStandardDepartmentConfig`에 옵션 필드 추가

2. **`src/strategies/skku-standard.ts`** — 두 곳에 분기 추가:

   **a) `crawlList()` — infoTexts 파싱 (line 50-63 부근)**:

   ```typescript
   // infoParser === 'labeled' 일 때
   // "POSTED DATE : 2026-03-20" → date
   // "WRITER : 화학과" → author
   // "HIT : 280" → views
   let author = '', date = '', views = 0;

   if (config.infoParser === 'labeled') {
     for (const text of infoTexts) {
       if (text.startsWith('POSTED DATE')) {
         date = text.replace(/^POSTED DATE\s*:\s*/, '');
       } else if (text.startsWith('WRITER')) {
         author = text.replace(/^WRITER\s*:\s*/, '');
       } else if (text.startsWith('HIT')) {
         const m = text.match(/(\d+)/);
         views = m ? parseInt(m[1], 10) : 0;
       }
     }
   } else {
     // 기존 인덱스 기반 파싱
     author = infoTexts[1] || '';
     date = infoTexts[2] || '';
     const viewsMatch = (infoTexts[3] || '0').match(/(\d+)/);
     views = viewsMatch ? parseInt(viewsMatch[1], 10) : 0;
   }
   ```

   **b) `crawlDetail()` — 첨부파일 파싱 (line 109-127 부근)**:

   ```typescript
   if (config.attachmentParser === 'onclick') {
     // 화학과: <button onclick="location.href='?mode=download&...'">파일명</button>
     $(config.selectors.attachmentList).each((_i, el) => {
       const $btn = $(el);
       const name = $btn.text().trim();
       const onclick = $btn.attr('onclick') || '';
       const match = onclick.match(/location\.href='([^']+)'/);
       if (name && match) {
         const fileUrl = match[1].replace(/&amp;/g, '&');
         const origin = new URL(config.baseUrl).origin;
         const fullUrl = fileUrl.startsWith('http') ? fileUrl
           : fileUrl.startsWith('?') ? `${config.baseUrl}${fileUrl}`
           : `${origin}${fileUrl.startsWith('/') ? '' : '/'}${fileUrl}`;
         attachments.push({ name, url: fullUrl });
       }
     });
   } else {
     // 기존 <a href="..."> 파싱
     $(config.selectors.attachmentList).each((_i, el) => { ... });
   }
   ```

3. **`src/config/departments.json`** — 화학과 엔트리 추가

### departments.json 최종 엔트리

```json
{
  "id": "chem",
  "name": "화학과",
  "strategy": "skku-standard",
  "baseUrl": "https://chem.skku.edu/chem/News/notice.do",
  "selectors": {
    "listItem": "ul.noticeList > li",
    "category": "",
    "titleLink": "h3.noticeTit a",
    "infoList": "ul.noticeInfoList li",
    "detailContent": "div.noticeViewCont",
    "attachmentList": "div.noticeViewBtnList button.fileBtn"
  },
  "infoParser": "labeled",
  "attachmentParser": "onclick",
  "pagination": {
    "type": "offset",
    "param": "article.offset",
    "limit": 10
  }
}
```

---

## 동일 템플릿 사용 가능성

`boardTy = 'chem_common'` + `/_custom/shb/` 리소스를 사용하는 학과가 더 있을 수 있다. 새로운 학과를 추가할 때 `noticeList` / `noticeListWrap` 클래스가 보이면 같은 `infoParser: "labeled"` + `attachmentParser: "onclick"` 옵션을 적용하면 된다.

확인 방법:
```bash
curl -s 'https://{dept}.skku.edu/...' | grep -o 'boardTy = [^,]*'
# 결과가 '{dept}_common' 이면 비표준 스킨일 가능성 높음
```

---

## 요약

| 항목 | 결론 |
|------|------|
| 새 전략 필요? | 불필요 (`skku-standard` 확장으로 충분) |
| 셀렉터만 변경으로 해결? | 불가 (infoList 파싱 + 첨부파일 파싱 로직이 다름) |
| 권장 방안 | `skku-standard`에 `infoParser` + `attachmentParser` 옵션 추가 |
| 변경 파일 수 | 3개 (`types.ts`, `skku-standard.ts`, `departments.json`) |
| URL/페이지네이션 호환 | 완전 호환 (동일한 SKKU CMS 기반) |
| articleNo 추출 | 동일 (`?mode=view&articleNo=N` 패턴) |
