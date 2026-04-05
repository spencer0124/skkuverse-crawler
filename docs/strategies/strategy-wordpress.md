# WordPress 게시판 크롤링 전략 (Type D)

## 사이트 개요

SKKU 일부 학과가 자체 WordPress 사이트를 운영하며, 공지사항도 WordPress 포스트로 관리한다.
현재 확인된 대상은 **화학공학과** (`cheme.skku.edu`) 1곳이며, 향후 다른 WordPress 기반 학과가 추가될 수 있다.

| 항목 | 내용 |
|------|------|
| 사이트 | https://cheme.skku.edu/notice/ |
| 플랫폼 | WordPress 6.5.8 |
| 테마 | Impreza (Visual Composer 기반) |
| 카테고리 구조 | `공지사항`(id:17, 696건), `취업정보`(id:30, 599건), `News`(id:19), `BK21 공지사항`(id:43) 등 |
| 페이지당 게시글 | 10건 |
| 총 페이지 | ~70 페이지 (공지사항 카테고리 기준) |

## 크롤링 방식: REST API vs HTML 파싱 vs RSS

WordPress는 3가지 데이터 접근 방식을 제공한다. **REST API 방식을 권장한다.**

### 방식 1: WP REST API (권장)

WordPress 내장 REST API(`wp/v2/posts`)가 **활성화되어 있음**을 확인했다.
단, `wp-json` 프리티 퍼머링크는 비활성이므로 `?rest_route=` 쿼리 파라미터를 사용해야 한다.

**장점:**
- JSON 응답 — HTML 파싱 불필요, DOM 변경에 영향 없음
- 구조화된 데이터 (id, title, date, content, categories, link 등)
- 페이지네이션 헤더 (`X-WP-Total`, `X-WP-TotalPages`) 제공
- 카테고리 필터링 가능 (`categories=17`)
- content 필드에 상세 본문 HTML 포함 — 상세 페이지 별도 fetch 불필요

**단점:**
- 사이트 관리자가 REST API를 비활성화하면 사용 불가 (현재는 활성)
- 첨부파일 정보가 content HTML에 임베드 — 별도 파싱 필요

### 방식 2: RSS Feed

RSS 2.0 피드가 활성화되어 있으며, 카테고리별 필터도 지원한다.

- 전체: `https://cheme.skku.edu/feed/`
- 카테고리별: `https://cheme.skku.edu/?feed=rss2&cat=17`

**RSS 아이템 구조:**
```xml
<item>
  <title>[대학원] 2026-1 논문제출자격시험 일정 및 시간표 안내</title>
  <link>https://cheme.skku.edu/2026/03/25/slug-here/</link>
  <dc:creator><![CDATA[영은 김]]></dc:creator>
  <pubDate>Wed, 25 Mar 2026 05:55:24 +0000</pubDate>
  <category><![CDATA[공지사항]]></category>
  <guid isPermaLink="false">https://cheme.skku.edu/?p=18750</guid>
  <description><![CDATA[요약 텍스트...]]></description>
</item>
```

**단점:** 최근 10건만 노출, 과거 게시글 크롤링 불가 → 초기 전체 크롤링에 부적합.
**용도:** REST API 비활성 사이트의 fallback, 또는 실시간 변경 감지용 보조 수단.

### 방식 3: HTML 파싱

Impreza 테마의 커스텀 CSS 클래스를 이용한 HTML 파싱. REST API 실패 시 fallback.

---

## REST API 상세 스펙

### 엔드포인트 패턴

```
GET {baseUrl}/?rest_route=/wp/v2/posts&per_page=10&page={page}&categories={catId}&_fields=id,title,date,link,content,categories
```

**주의:** `wp-json` 프리티 URL이 비활성이므로 반드시 `?rest_route=` 쿼리 방식을 사용해야 한다.

```
# 동작하지 않음 (404)
https://cheme.skku.edu/wp-json/wp/v2/posts

# 동작함
https://cheme.skku.edu/?rest_route=/wp/v2/posts&per_page=10&page=1&categories=17
```

### 응답 구조

```json
[
  {
    "id": 18750,
    "date": "2026-03-25T14:55:24",
    "title": { "rendered": "[대학원] 2026-1 논문제출자격시험 일정 및 시간표 안내" },
    "link": "https://cheme.skku.edu/2026/03/25/slug-here/",
    "content": { "rendered": "<p>본문 HTML...</p>" },
    "categories": [17]
  }
]
```

### 페이지네이션

- **응답 헤더:** `X-WP-Total` (전체 게시글 수), `X-WP-TotalPages` (전체 페이지 수)
- **쿼리 파라미터:** `page=N` (1-based), `per_page=10` (최대 100)
- **빈 페이지:** 범위 초과 시 HTTP 400 에러 반환
- **incremental 전략:** 1페이지부터 시작, DB에 모든 articleNo가 있는 페이지를 만나면 중단

### articleNo 추출

WordPress의 `id` 필드가 그대로 `articleNo`로 사용된다.
- REST API: `post.id` → `18750`
- RSS guid: `https://cheme.skku.edu/?p=18750` → 정규식 `[?&]p=(\d+)` 으로 추출
- URL slug에서는 추출 불가 (slug는 한글 인코딩된 제목)

### 카테고리 정보

```
GET {baseUrl}/?rest_route=/wp/v2/categories&per_page=100&_fields=id,name,slug,count
```

```json
[
  { "id": 17, "name": "공지사항", "slug": "notice", "count": 696 },
  { "id": 30, "name": "취업정보", "slug": "career", "count": 599 },
  { "id": 19, "name": "News", "slug": "news", "count": 255 },
  { "id": 43, "name": "BK21 공지사항", "slug": "bk21-notice", "count": 26 },
  { "id": 1, "name": "Uncategorized", "slug": "uncategorized", "count": 41 }
]
```

카테고리 ID를 `departments.json`의 `categoryId` 필드에 지정하여 필터링한다.

### 필드 매핑 (REST API → NoticeListItem)

| REST API 필드 | NoticeListItem 필드 | 변환 |
|---------------|---------------------|------|
| `id` | `articleNo` | 그대로 |
| `title.rendered` | `title` | HTML 엔티티 디코딩 |
| `date` | `date` | `YYYY-MM-DDTHH:mm:ss` → `YYYY-MM-DD` |
| `link` | `detailPath` | 절대 URL 그대로 |
| `categories[0]` → 카테고리 맵 조회 | `category` | ID → 이름 변환 |
| — | `author` | `""` (REST API에서 `_embed` 없으면 작성자 이름 없음) |
| — | `views` | `0` (WordPress 기본 조회수 없음) |

### 필드 매핑 (REST API → NoticeDetail)

| REST API 필드 | NoticeDetail 필드 | 변환 |
|---------------|-------------------|------|
| `content.rendered` | `content` | 그대로 (HTML) |
| `content.rendered` | `contentText` | cheerio `.text()` |
| `content.rendered` 내 `<a>` | `attachments` | PDF/파일 링크 추출 |

**핵심:** REST API에서 `content` 필드를 포함하면 **목록과 상세를 1번의 API 호출로 모두 가져올 수 있다.**
상세 페이지 별도 fetch가 불필요하므로 기존 `crawlList()` + `crawlDetail()` 2단계를 1단계로 단축할 수 있다.

---

## HTML 파싱 상세 (REST API 실패 시 Fallback)

### 목록 페이지 구조

URL: `https://cheme.skku.edu/notice/` (이후 `/notice/page/2/`, `/notice/page/3/`, ...)

```html
<!-- Impreza 테마 그리드 시스템 -->
<div class="w-grid-item-h">
  <h3 class="usg_post_title_1">
    <a href="https://cheme.skku.edu/2026/03/25/slug-here/">게시글 제목</a>
  </h3>
  <div class="usg_hwrapper_1">2026-03-25</div>
  <div class="usg_post_content_1">카테고리 또는 발췌문</div>
</div>
```

### 목록 페이지 CSS 셀렉터

| 요소 | 셀렉터 |
|------|--------|
| 게시글 래퍼 | `div.w-grid-item-h` |
| 제목 링크 | `h3.usg_post_title_1 a` |
| 날짜 | `div.usg_hwrapper_1` |
| 카테고리/발췌 | `div.usg_post_content_1` |
| 전체 컨테이너 | `div.layout_7830` |

### 목록 페이지 주의사항

- **articleNo 추출 불가:** HTML 목록에는 WordPress post ID가 노출되지 않음.
  slug URL만 있으므로 별도의 상세 페이지 fetch에서 post ID를 추출해야 함.
  (body 태그의 `postid-XXXX` 클래스 또는 상세 페이지 내 `?p=XXXX` 패턴)
- **작성자/조회수 없음:** 목록 페이지에 author, views 정보 미노출.
- **`usg_` 클래스는 테마 빌더 생성값:** 사이트마다 다를 수 있음 (`usg_post_title_1` vs `usg_post_title_2` 등).

### 페이지네이션 (HTML)

```
/notice/          → 1페이지
/notice/page/2/   → 2페이지
/notice/page/N/   → N페이지
```

- WordPress 표준 프리티 퍼머링크 방식: `/page/{N}/`
- 이전/다음 링크: `이전` (한글), `다음` (한글)
- 현재 페이지: 링크 없는 plain text
- 총 70페이지 (공지사항 카테고리)

### 상세 페이지 구조

URL 패턴: `https://cheme.skku.edu/{YYYY}/{MM}/{DD}/{slug}/`

```html
<body class="single single-post postid-18750 ...">
  <div class="l-main">
    <div class="l-section">
      <!-- 제목 -->
      <h1>게시글 제목</h1>

      <!-- 메타 정보 -->
      <div>2026-03-25 · 공지사항 · #대학원</div>

      <!-- 본문 -->
      <div class="entry-content">
        <p>본문 텍스트...</p>
        <!-- 첨부파일 링크 -->
        <a href="https://cheme.skku.edu/.../file.pdf">파일명.pdf</a>
      </div>
    </div>
  </div>
</body>
```

### 상세 페이지 CSS 셀렉터

| 요소 | 셀렉터 | 비고 |
|------|--------|------|
| 본문 컨테이너 | `div.entry-content` | Impreza 테마 표준 |
| 제목 | `h1` (페이지 내 첫 번째) | |
| post ID | `body[class*="postid-"]` | 정규식 `postid-(\d+)` 으로 추출 |
| 첨부파일 | `div.entry-content a[href$=".pdf"], a[href$=".hwp"], a[href$=".xlsx"]` | 확장자 기반 필터 |

---

## 전략 구현 설계

### 권장: REST API 기반 (`wordpress-api` 전략)

```typescript
// strategies/wordpress-api.ts

export const wordpressApiStrategy: CrawlStrategy = {
  async crawlList(config, page) {
    const { baseUrl, categoryId } = config;
    const params = new URLSearchParams({
      rest_route: '/wp/v2/posts',
      per_page: '10',
      page: String(page),
      _fields: 'id,title,date,link,content,categories',
      ...(categoryId ? { categories: String(categoryId) } : {}),
    });

    const url = `${baseUrl}/?${params}`;
    const res = await fetcher.get(url);
    // res.headers['x-wp-totalpages'] 로 마지막 페이지 판단

    return res.data.map(post => ({
      articleNo: post.id,
      title: decodeEntities(post.title.rendered),
      category: categoryMap.get(post.categories[0]) ?? '',
      author: '',    // REST API 기본 응답에 없음
      date: post.date.split('T')[0],  // "2026-03-25T14:55:24" → "2026-03-25"
      views: 0,      // WordPress 기본 조회수 없음
      detailPath: post.link,
    }));
  },

  async crawlDetail(ref, config) {
    // REST API에서 이미 content를 가져왔으므로,
    // crawlList에서 content도 함께 반환하는 확장 방식 사용 가능.
    // 또는 단건 조회:
    const url = `${config.baseUrl}/?rest_route=/wp/v2/posts/${ref.articleNo}&_fields=content`;
    const res = await fetcher.get(url);
    const html = res.data.content.rendered;
    const $ = loadHtml(html);
    return {
      content: html,
      contentText: $.text().trim(),
      attachments: extractAttachments($, config.baseUrl),
    };
  },
};
```

### 최적화: 목록 + 상세 통합 크롤링

REST API에서 `_fields`에 `content`를 포함하면, 목록 API 호출 1번에 모든 데이터를 가져올 수 있다.
이 경우 `crawlDetail()`을 호출할 필요가 없어 HTTP 요청 수가 **N+1 → 1**로 줄어든다.

```typescript
// crawlList에서 content까지 포함하는 확장 인터페이스
interface WordPressListResult {
  items: NoticeListItem[];
  details: Map<number, NoticeDetail>;  // articleNo → detail
}
```

기존 `CrawlStrategy` 인터페이스와의 호환성을 위해:
1. `crawlList()`에서 content를 메모리 캐시에 저장
2. `crawlDetail()`에서 캐시 히트 시 즉시 반환, 미스 시 단건 API 호출

### Fallback: HTML 파싱 전략

REST API가 비활성화된 WordPress 사이트를 위한 fallback.
`usg_` 클래스가 사이트마다 다를 수 있으므로 `selectors`를 departments.json에서 설정한다.

---

## departments.json 설정 예시

### REST API 방식 (권장)

```json
{
  "id": "cheme",
  "name": "화학공학과",
  "strategy": "wordpress-api",
  "baseUrl": "https://cheme.skku.edu",
  "categoryId": 17,
  "pagination": {
    "type": "pageNum",
    "param": "page",
    "limit": 10
  }
}
```

### 카테고리별 분리 등록 (선택)

공지사항과 취업정보를 별도 소스로 분리할 경우:

```json
[
  {
    "id": "cheme-notice",
    "name": "화학공학과(공지)",
    "strategy": "wordpress-api",
    "baseUrl": "https://cheme.skku.edu",
    "categoryId": 17,
    "pagination": { "type": "pageNum", "param": "page", "limit": 10 }
  },
  {
    "id": "cheme-career",
    "name": "화학공학과(취업)",
    "strategy": "wordpress-api",
    "baseUrl": "https://cheme.skku.edu",
    "categoryId": 30,
    "pagination": { "type": "pageNum", "param": "page", "limit": 10 }
  }
]
```

### HTML Fallback 방식

```json
{
  "id": "cheme",
  "name": "화학공학과",
  "strategy": "wordpress-html",
  "baseUrl": "https://cheme.skku.edu/notice",
  "selectors": {
    "listItem": "div.w-grid-item-h",
    "titleLink": "h3.usg_post_title_1 a",
    "date": "div.usg_hwrapper_1",
    "excerpt": "div.usg_post_content_1",
    "detailContent": "div.entry-content"
  },
  "pagination": {
    "type": "wpPage",
    "pattern": "/page/{N}/"
  }
}
```

---

## 타입 정의 확장

```typescript
// types.ts 추가 사항

export interface WordPressApiDepartmentConfig extends BaseDepartmentConfig {
  strategy: 'wordpress-api';
  categoryId?: number;          // WP 카테고리 ID (없으면 전체)
  pagination: PageNumPaginationConfig;
}

export interface WordPressHtmlDepartmentConfig extends BaseDepartmentConfig {
  strategy: 'wordpress-html';
  selectors: {
    listItem: string;
    titleLink: string;
    date: string;
    excerpt: string;
    detailContent: string;
  };
  pagination: {
    type: 'wpPage';
    pattern: string;   // "/page/{N}/"
  };
}

export type DepartmentConfig =
  | SkkuStandardDepartmentConfig
  | WordPressApiDepartmentConfig
  | WordPressHtmlDepartmentConfig;
```

---

## 특수 고려사항

### 1. `wp-json` 프리티 URL 비활성

`cheme.skku.edu`는 `/wp-json/wp/v2/posts`로 접근하면 404를 반환한다.
반드시 `?rest_route=/wp/v2/posts` 쿼리 방식을 사용해야 한다.
새 WordPress 사이트 추가 시 두 방식 모두 체크하여 동작하는 쪽을 사용해야 한다.

```typescript
// REST API 엔드포인트 탐지 로직
async function detectRestEndpoint(baseUrl: string): Promise<string> {
  // 1차: 프리티 URL
  try {
    await fetcher.get(`${baseUrl}/wp-json/wp/v2/posts?per_page=1`);
    return `${baseUrl}/wp-json/wp/v2/posts`;
  } catch {
    // 2차: 쿼리 파라미터 방식
    const res = await fetcher.get(`${baseUrl}/?rest_route=/wp/v2/posts&per_page=1`);
    if (res.status === 200) return `${baseUrl}/?rest_route=/wp/v2/posts`;
    throw new Error(`REST API not available at ${baseUrl}`);
  }
}
```

### 2. HTML 엔티티 디코딩

`title.rendered`에 HTML 엔티티가 포함될 수 있다 (`&amp;`, `&#8211;`, `&lt;` 등).
cheerio 또는 `he` 라이브러리로 디코딩 필요.

```typescript
import { decode } from 'he';
const title = decode(post.title.rendered);  // "KT&amp;G" → "KT&G"
```

### 3. 작성자 정보

REST API 기본 응답에 작성자 이름이 없다. 필요 시 `_embed` 파라미터를 추가하면 `_embedded.author[0].name`으로 가져올 수 있으나, 응답 크기가 커진다.

```
?rest_route=/wp/v2/posts&_embed&_fields=id,title,date,link,content,_embedded
```

현재 화학공학과의 작성자는 조교(김영은) 한 명이므로 실익이 적다. `author: ""`로 처리.

### 4. 조회수

WordPress 기본 기능에 조회수가 없다. 플러그인(WP-PostViews, Post Views Counter 등)이 설치되어 있으면 REST API에 커스텀 필드로 노출될 수 있으나, 현재 사이트에서는 확인되지 않음. `views: 0`으로 처리.

### 5. 첨부파일 추출

`content.rendered` HTML 내에서 파일 링크를 추출해야 한다.
WordPress 미디어 라이브러리 URL 패턴:

```
https://cheme.skku.edu/wp-content/uploads/2026/03/filename.pdf
```

```typescript
function extractAttachments($: CheerioAPI, baseUrl: string): { name: string; url: string }[] {
  const fileExtensions = /\.(pdf|hwp|hwpx|xlsx|xls|docx|doc|pptx|ppt|zip)$/i;
  const attachments: { name: string; url: string }[] = [];

  $('a[href]').each((_, el) => {
    const href = $(el).attr('href') ?? '';
    if (fileExtensions.test(href)) {
      attachments.push({
        name: $(el).text().trim() || href.split('/').pop() || 'unknown',
        url: href.startsWith('http') ? href : new URL(href, baseUrl).href,
      });
    }
  });

  return attachments;
}
```

### 6. 날짜 형식

REST API의 `date` 필드는 사이트 로컬 시간대(Asia/Seoul) 기준 ISO 형식이다.
UTC가 필요하면 `date_gmt` 필드를 사용한다.

```
date: "2026-03-25T14:55:24"       ← KST (Asia/Seoul)
date_gmt: "2026-03-25T05:55:24"   ← UTC
```

Notice 스키마의 `date`는 `YYYY-MM-DD`이므로 `post.date.split('T')[0]`으로 변환.

### 7. 다른 WordPress 학과 추가 시 체크리스트

새 WordPress 기반 학과를 추가할 때 확인할 사항:

1. **REST API 활성 여부:** `{baseUrl}/wp-json/` 또는 `{baseUrl}/?rest_route=/` 접근 테스트
2. **REST API URL 방식:** 프리티(`/wp-json/`) vs 쿼리(`?rest_route=`)
3. **카테고리 목록 조회:** `?rest_route=/wp/v2/categories&per_page=100` → 공지사항 카테고리 ID 확인
4. **RSS 피드 활성 여부:** `{baseUrl}/feed/` → REST API 비활성 시 대안
5. **테마 및 CSS 클래스:** HTML fallback 시 셀렉터 확인 (테마마다 다름)
6. **한글 slug:** URL에 한글 slug가 포함될 수 있음 (percent-encoding 처리 필요)

---

## 구현 우선순위

1. **`wordpress-api` 전략 구현** — REST API 기반, content 포함 통합 크롤링
2. **`cheme` 설정 추가** — departments.json에 화학공학과 등록
3. **verify-selectors 확장** — WordPress REST API 응답 검증 로직 추가
4. **(선택) `wordpress-html` 전략** — REST API 비활성 사이트용 fallback
5. **(선택) RSS 모니터링** — 실시간 변경 감지용 보조 수단
