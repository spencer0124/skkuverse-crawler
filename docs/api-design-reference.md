# 공지 API 설계를 위한 크롤러 데이터 레퍼런스

## Context

앱에서 SKKU 공지를 표시하기 위한 API를 설계하려 한다. 이 문서는 그 전제가 되는 크롤러의 저장 구조, 유형별 특이사항, 실제 예시 데이터를 한눈에 볼 수 있도록 정리한 레퍼런스다. (실제 `skku_notices` DB의 샘플 데이터로 검증함.)

---

## 1. 저장 구조 한눈에

- **MongoDB DB**: `skku_notices` (prod) / `skku_notices_dev` / `skku_notices_test`
- **컬렉션**: `notices` (단일. 모든 학과/기숙사/공지 통합)
- **문서 식별**: `(articleNo, sourceDeptId)` 복합 unique
- **인덱스** (실측):
  - `articleNo_1_sourceDeptId_1` (unique)
  - `sourceDeptId_1_date_-1` (학과별 최신순 리스트 쿼리용)
  - `idx_summary_pending` = `{summaryAt:1, contentText:1}` (요약 배치용)

앱 API가 쓸 수 있는 기본 패턴:
- 학과별 최신순 리스트 → `{sourceDeptId}` 필터 + `date DESC` 정렬 (인덱스 적중)
- 전체 최신순 → 별도 인덱스 없음. 추가 인덱스 필요 (`date_-1` 또는 `crawledAt_-1`)
- 검색 → 현재 text 인덱스 없음 (설계 시 고려 필요)

---

## 2. 필드 전체 목록 (Notice 문서)

`py/src/skkuverse_crawler/notices/models.py:26-48` + 요약 프로세서가 `$set`으로 덧붙이는 필드.

### 2.1 크롤러가 쓰는 필드 (모든 문서에 존재)

| 필드 | 타입 | 설명 |
|---|---|---|
| `articleNo` | int | 원 사이트의 게시글 번호 (학과 내에서만 unique) |
| `sourceDeptId` | string | 학과 config id (`skku-main`, `cheme`, `dorm-hssc`, …) |
| `department` | string | 학과 사람 이름 (`학부통합(학사)`, `화학공학과` …) |
| `title` | string | 공지 제목 |
| `category` | string | 원 사이트 카테고리 (전략별로 있을 수도/빈 문자열일 수도) |
| `author` | string | 작성자 (전략별로 있을 수도/빈 문자열일 수도) |
| `date` | string | **`YYYY-MM-DD` 문자열** (Date 타입 아님 — 정렬·비교 주의) |
| `views` | int | 조회수 (전략별로 0일 수도) |
| `content` | string\|null | **원본 HTML + 절대 URL** (정제 전). 레거시 렌더 경로. backfill의 입력 소스 |
| `cleanHtml` | string\|null | 6단계 파이프라인으로 정제된 HTML(nh3 화이트리스트). 5MB 초과 시 null. 해시 산출 기준 |
| **`cleanMarkdown`** | string\|null | `cleanHtml` → GFM 변환 결과. **앱 마크다운 렌더 권장 소스**. cleanHtml이 null이면 null |
| `contentText` | string\|null | `cleanHtml`에서 뽑은 plain text. **블록 경계 `\n` 보존** (검색/요약 입력/미리보기용) |
| `attachments` | `[{name,url}]` | 첨부파일. 비어있을 수 있음. URL은 절대경로 |
| `sourceUrl` | string | 원 게시글 상세 URL (외부 열기 링크로 사용) |
| `detailPath` | string | 리스트에서 얻은 상대/쿼리. 내부 재크롤 용도. **앱에 노출 불필요** |
| `contentHash` | string\|null | `cleanHtml`의 SHA256. null = 컨텐츠 미확보 |
| `crawledAt` | datetime (UTC) | 마지막 크롤 시각 |
| `backfilledAt` | datetime (UTC)\|absent | backfill로 소급 갱신된 문서에만 존재. 신규 크롤링 문서엔 없음 |
| `lastModified` | null | 현재 미사용 (예약 필드) |
| `isDeleted` | bool | 원본에서 사라지면 soft delete |
| `consecutiveFailures` | int | 상세 fetch 실패 연속 횟수 (앱 노출 불필요) |
| `editHistory` | array | 최근 20개 수정 기록 (아래 §5 참조) |
| `editCount` | int | 총 수정 횟수 |

**본문 필드 선택 가이드**:

- **마크다운 렌더러를 쓰는 앱** → `cleanMarkdown` (1순위). GFM 지원 필수 (테이블·이미지·링크 다 등장). 없으면 `cleanHtml` fallback
- **웹뷰 HTML 렌더** → `cleanHtml`. 이미 sanitize되어 안전
- **검색·요약·미리보기** → `contentText` (줄바꿈이 필요 없으면 `\n`을 공백으로 치환)
- **`content`는 사용 지양** — 크기 크고 sanitize 안 됨. backfill용 입력 소스로만 존재

**크기 실측 (prod 126건 기준)**:
| 필드 | 평균 | 최대 |
|---|---:|---:|
| `cleanMarkdown` | ~1.2 KB | ~6.3 KB |
| `cleanHtml` | ~6 KB | 수백 KB |
| `content` | 편차 큼 | MB 단위 가능 |

### 2.2 요약 프로세서가 덧붙이는 필드 (있을 수도/없을 수도)

`notices_summary/processor.py:83-101` 기준. 요약이 완료된 문서에만 존재.

| 필드 | 타입 | 설명 |
|---|---|---|
| `summary` | string | 본문 요약. 친근한 톤("~요") |
| `summaryOneLiner` | string | 한 줄 요약. 보통 `"YYYY-MM-DD ..."` 형식으로 시작 |
| `summaryType` | string | 분류. 실측값: `action_required`, `informational` (AI가 자유롭게 생성하므로 enum으로 단정 불가) |
| `summaryStartDate` / `summaryEndDate` | string\|null | `YYYY-MM-DD` |
| `summaryStartTime` / `summaryEndTime` | string\|null | `HH:MM` |
| `summaryDetails` | object\|null | 구조화 필드. 실측 키: `target`, `action`, `location`, `host`, `impact` (각 null 가능) |
| `summaryModel` | string | 예: `gpt-4.1-mini-2025-04-14` |
| `summaryAt` | datetime | 요약 생성 시각 |
| `summaryContentHash` | string | 요약 생성 시점의 `contentHash`. 본문이 바뀌면 stale 판단에 사용 |
| `summaryFailures` | int | 요약 실패 카운터. ≥3이면 재시도 중단 |

**요약 없음 상태를 판별하는 조건** (앱에서 "요약 준비 중" 표시):
```
summaryAt 필드 없음 OR summaryAt == null
```
`contentText`가 null이면 애초에 요약 불가 → 영영 요약 안 달림.

**요약이 stale한 상태** (본문 수정 후 재요약 대기):
```
summaryContentHash != contentHash
```
앱이 굳이 알 필요는 없지만, "업데이트됨" 배지 내는 데 활용 가능.

---

## 3. 전략(strategy) 7종 · 유형별 특이사항

`departments.json` 기준 전략별 실측 분포 (학과 수는 `departments.json` 참조):

| strategy | 학과 수 | category | author | views | content | 비고 |
|---|---:|:---:|:---:|:---:|:---:|---|
| `skku-standard` | 134 | ✓ | ✓ | ✓ | ✓ | 대부분. 품질 가장 좋음 |
| `gnuboard` | 3 | ✗ | ✓ | ✓ | ✓ | 생명과/약대 등 |
| `jsp-dorm` | 2 | △ | ✗ | ✗ | ✓ | 명륜·봉룡학사. `category`는 "Notice in English" 처럼 들어오기도 함 |
| `custom-php` | 2 | ✓ | ✗ | ✓ | ✓ | 건설환경공학부 |
| `wordpress-api` | 1 | ✗ | ✗ | ✗ | ✓ | 화학공학과. WP REST API |
| `skkumed-asp` | 1 | ✗ | ✓ | ✓ | ✓ | 의과대학. EUC-KR 인코딩 |
| `gnuboard-custom` | 1 | ✗ | △ | ✓ | ✓ | 나노공학과. author="관리자" 같이 들어옴 |

"✗"인 필드는 대부분 **빈 문자열 `""`** (null 아님). 앱에서는 `if (category)` 체크로 숨겨야 함.

### 3.1 앱 설계 시 반드시 알아야 할 점

1. **`date`는 문자열 `YYYY-MM-DD`**. `new Date()` 변환 OK지만 정렬·범위 쿼리는 문자열 비교(사전순=연대순이라 문제는 없음).
2. **`content` 없음** 케이스가 실존: 상세 fetch 실패 시 `content/cleanHtml/cleanMarkdown/contentHash = null`. 앱은 "본문 준비 중" 또는 `sourceUrl`로 외부 링크만 제공해야 함.
3. **`cleanHtml` 5MB 초과** 시에도 null이 됨 (드물지만 가능). 이 경우 `cleanMarkdown`도 null.
4. **`category`/`author`/`views`는 전략별로 빈값** — 학과별 뷰에서 조건부 렌더 필요. 전체 리스트 뷰에서는 위 테이블을 바탕으로 "category가 보장되는 학과"만 카테고리 필터 제공 가능.
5. **중복 키는 `(articleNo, sourceDeptId)`** — `articleNo` 단독은 전혀 unique하지 않음. 앱 API의 상세 엔드포인트는 `/notices/:deptId/:articleNo` 형태가 자연스러움.
6. **`attachments[].url`은 절대경로** 로 저장되어 있으니 앱에서 그대로 외부 브라우저로 열면 됨.
7. **`cleanHtml`은 이미 sanitize됨** (nh3). 허용 태그: `p, br, div, span, h1-h4, strong, b, em, i, u, mark, ul, ol, li, table, thead, tbody, tr, th, td, img, a, hr`. 스타일: `color, background-color, text-align, text-decoration, font-weight, font-style`만. 앱의 웹뷰/HTML 렌더에서 그대로 쓰면 안전. `content`(원본)는 sanitize 안 된 상태라 그대로 주입하지 말 것.
8. **`cleanMarkdown`은 GFM** — ATX heading(`#~####`), `**bold**`, `*em*`, `- ` / `1. ` 리스트, GFM 테이블(`| --- |`), `![alt](src)` 이미지, `[text](href)` 링크, `  \n` hard break. `<u>`, `<mark>`, `text-align`, `background-color` 같은 장식성 스타일은 손실됨. colspan/rowspan도 단순화됨(10% 문서). 앱 렌더러는 GFM 테이블과 원격 이미지 지원 필수.
9. **`contentText`의 줄바꿈**: 2026-04 이후 문서는 블록 경계가 `\n`으로 분리된다. 이전 backfill 안 된 구 문서는 공백으로 뭉개져 있을 수 있음. 미리보기 UI는 `white-space: pre-wrap` 또는 `\n`→ 공백 치환으로 대응.
8. **첨부파일 이름**은 원본 그대로 (한글·공백 포함). URL 인코딩은 되어있지 않으므로 필요 시 클라이언트에서.
9. **`isDeleted: true`**는 원본 삭제된 공지 → 앱 리스트에서 기본 제외 권장.
10. **요약 톤**은 고정 ("~요" 체). 앱 UI 톤과 안 맞으면 프롬프트 수정이 크롤러 쪽 작업.

---

## 4. 실제 예시 데이터 (DB에서 뽑은 real sample)

> 긴 `content`/`cleanHtml` 필드는 생략. 나머지는 실제 값.

### 4.1 skku-standard (학부통합, 요약 완료, 제목 2회 수정됨)

```json
{
  "articleNo": 136023,
  "sourceDeptId": "skku-main",
  "department": "학부통합(학사)",
  "title": "[모집] 2026 학생 창업유망팀 300+ 사전준비반 참가팀 모집 [마감]",
  "category": "행사/세미나",
  "author": "안찬웅",
  "date": "2026-04-10",
  "views": 7865,
  "attachments": [
    {"name": "붙임. 2026 학생 창업유망팀 300+ 공고문.pdf",
     "url": "https://www.skku.edu/skku/campus/skk_comm/notice01.do?mode=download&articleNo=136023&attachNo=113301"},
    {"name": "2026년 성균관대학교 창업지원단 학생창업유망팀 U300+ 사전준비반 공고문.hwp", "url": "..."},
    {"name": "[첨부 1] 2026년 학생창업유망팀 U300+ 사전준비반_신청서 및 사업계획서.hwp", "url": "..."}
  ],
  "contentText": "성균인 여러분, 안녕하세요! \n성균관대학교 창업지원단입니다. \n\n...",
  "contentHash": "c0b3d6e4...82c9",
  "sourceUrl": "https://www.skku.edu/skku/campus/skk_comm/notice01.do?mode=view&articleNo=136023&article.offset=0&articleLimit=10",
  "crawledAt": "2026-04-10T03:00:02.067Z",
  "isDeleted": false,
  "editCount": 2,
  "editHistory": [
    {"detectedAt":"2026-04-09T08:00:00Z",
     "oldTitle":"[모집] 2026 학생 창업유망팀 300+ 사전준비반 참가팀 모집",
     "newTitle":"[모집] 2026 학생 창업유망팀 300+ 사전준비반 참가팀 모집 [오늘 마감]",
     "titleChanged":true,"contentChanged":false,"source":"tier1"},
    {"detectedAt":"2026-04-10T01:30:00Z",
     "oldTitle":"... [오늘 마감]","newTitle":"... [마감]",
     "titleChanged":true,"contentChanged":false,"source":"tier1"}
  ],

  "summary": "성균관대학교 창업지원단에서 2026 학생 창업유망팀 300+ 사전준비반 참가팀을 4월 9일까지 모집해요. 3~5인 팀 구성으로 신청서 작성 후 구글폼에 제출해야 하며, 본선 진출 시 창업지원금과 우대 혜택이 있어요. 혁신적인 아이디어를 가진 학생 창업팀은 꼭 참여해 보세요.",
  "summaryOneLiner": "2026-04-09까지 학생 창업유망팀 300+ 사전준비반 신청",
  "summaryType": "action_required",
  "summaryStartDate": "2026-04-03",
  "summaryEndDate": "2026-04-09",
  "summaryStartTime": null,
  "summaryEndTime": null,
  "summaryDetails": {
    "target": "성균관대학교(원) 소속 학생 2인 이상 팀",
    "action": "신청서 작성 후 구글폼에 제출",
    "location": null,
    "host": "성균관대학교 창업지원단",
    "impact": "본선 진출 시 창업지원금 및 우대 혜택"
  },
  "summaryModel": "gpt-4.1-mini-2025-04-14",
  "summaryAt": "2026-04-09T11:52:02.769Z",
  "summaryContentHash": "c0b3d6e4...82c9",
  "summaryFailures": 0
}
```

주목할 점:
- 제목 태그(`[마감]`, `[오늘 마감]`)가 시간 경과로 바뀌는 패턴이 **실제로 빈번**. 앱의 "수정 표시" 처리 필요.
- `source: "tier1"`은 리스트 스캔에서 발견된 변경. `tier2`는 content-only 변경 감지 (아래 4.2 참조).

### 4.2 wordpress-api (화학공학과, category/author 빈값, content만 변경되는 tier2 수정)

```json
{
  "articleNo": 18867,
  "sourceDeptId": "cheme",
  "department": "화학공학과",
  "title": "[학부/대학원] 2026학년도 1학기 중간시험 및 중간강의평가 시행 안내",
  "category": "",
  "author": "",
  "date": "2026-04-07",
  "views": 0,
  "attachments": [],
  "contentText": "2026학년도 1학기 중간시험 및 중간강의평가를 ...",
  "contentHash": "ab4e8ef2...b877",
  "sourceUrl": "https://cheme.skku.edu/2026/04/07/.../",
  "editCount": 1,
  "editHistory": [
    {"detectedAt":"2026-04-09T09:42:26Z",
     "oldHash":"6b79d6c1...2400","newHash":"ab4e8ef2...b877",
     "contentChanged":true,"source":"tier2"}
  ],
  "summary": "2026학년도 1학기 중간시험과 중간강의평가가 4월 20일부터 5월 1일까지 진행돼요. ...",
  "summaryOneLiner": "2026-04-20~05-01 중간시험 및 중간강의평가 시행",
  "summaryType": "informational",
  "summaryStartDate": "2026-04-20",
  "summaryEndDate": "2026-05-01",
  "summaryDetails": {"target":"학부 및 대학원 학생","action":null,"location":null,"host":null,"impact":"시험 및 평가 공정성 확보를 위해 협조 필요"},
  "summaryModel": "gpt-4.1-mini-2025-04-14"
}
```

주목할 점:
- `category: ""`, `author: ""`, `views: 0` — WP 전략 한계.
- tier2 edit은 title 안 바뀌고 본문만 바뀜 (`titleChanged` 필드 자체 없음, `contentChanged:true`).
- `attachments: []` — WP 본문 내 파일이 없는 경우.

### 4.3 jsp-dorm (명륜학사, category="Notice in English", 영어 본문)

```json
{
  "articleNo": 86439,
  "sourceDeptId": "dorm-hssc",
  "department": "명륜학사 (인사캠 기숙사)",
  "title": "Suspending Curfew during mid-term exam period",
  "category": "Notice in English",
  "author": "",
  "date": "2026-04-07",
  "views": 86,
  "attachments": [],
  "contentText": "There is no admission control during the exam ...",
  "sourceUrl": "https://dorm.skku.edu/dorm_seoul/notice/notice_all.jsp?mode=view&article_no=86439&...",
  "editCount": 0,

  "summary": "4월 13일부터 26일까지 기숙사 통금이 해제돼요. ...",
  "summaryOneLiner": "2026-04-13~04-26 기숙사 통금 해제 안내",
  "summaryType": "informational",
  "summaryStartDate": "2026-04-13",
  "summaryEndDate": "2026-04-26",
  "summaryDetails": {"target":"C/E/G/K/M-House Residents","action":null,"location":null,"host":null,"impact":"기숙사 24시간 출입 가능으로 ..."}
}
```

주목할 점:
- 원문은 **영어**인데 요약은 **한국어**. 앱에서 요약을 보여주면 언어 불일치가 자연스럽게 해결됨.
- `category`가 "Notice in English"처럼 쓰이는 경우 존재 → 카테고리 필터 UI로 영어 공지를 분리할 수도 있음.

### 4.4 gnuboard-custom (나노공학과, author="관리자", 이미지 첨부)

```json
{
  "articleNo": 427,
  "sourceDeptId": "nano",
  "department": "나노공학과",
  "title": "[취업][기아] 2026상반기 기아 신입/전환형 인턴 채용 (신입 ~4/13(월) 11시, 인턴 ~4/20(월) 11시까지)",
  "category": "",
  "author": "관리자",
  "date": "2026-04-09",
  "views": 35,
  "attachments": [
    {"name":"2026 상반기 기아 신입 채용.png","url":"https://nano.skku.edu/bbs/download.php?tbl=bbs42&no=429"},
    {"name":"2026 상반기 기아 전환형 인턴 채용.png","url":"https://nano.skku.edu/bbs/download.php?tbl=bbs42&no=430"}
  ],
  "sourceUrl": "https://nano.skku.edu/bbs/board.php?mode=view&articleNo=427",
  "editCount": 1,
  "editHistory": [{"contentChanged":true,"source":"tier2", "...":"..."}],

  "summaryType": "action_required",
  "summaryStartDate": "2026-04-01",
  "summaryStartTime": "11:00",
  "summaryEndDate": "2026-04-20",
  "summaryEndTime": "11:00",
  "summaryOneLiner": "2026-04-13, 04-20 기아 신입·전환형 인턴 채용",
  "summaryDetails": {"target":"신입: 학/석사 ...","action":"기아 탤런트 라운지에서 온라인 지원","host":"기아"}
}
```

주목할 점:
- `summaryStartTime`/`EndTime`에 실제 시각이 들어온 예시 (일반 공지엔 대부분 null).
- 첨부가 PNG 포스터뿐 — 앱에서는 첨부 이미지를 본문 대체로 보여주는 폴백 UI도 고려할 만함.

---

## 5. editHistory 구조 (앱 "업데이트됨" 배지 설계 참고)

최근 20개까지 push. 두 종류의 엔트리가 섞여 있다:

**tier1** (리스트 재스캔에서 title 또는 date 변경 감지):
```json
{
  "detectedAt": "...",
  "oldHash": "...", "newHash": "...",
  "oldTitle": "...", "newTitle": "...",
  "titleChanged": true|false,
  "contentChanged": true|false,
  "source": "tier1"
}
```

**tier2** (body만 변경 감지, 제목 필드 없음):
```json
{
  "detectedAt": "...",
  "oldHash": "...", "newHash": "...",
  "contentChanged": true,
  "source": "tier2"
}
```

앱에서:
- "최근 수정" 표시 기준: `editCount > 0` AND 가장 최근 `editHistory[-1].detectedAt`이 N시간 이내
- "제목 변경됨" 표시: `editHistory` 마지막 엔트리의 `titleChanged: true`
- 상세화면에서 "변경 이력 N회" 클릭 시 history 펼쳐주는 UX 가능

---

## 6. 요약(summary) 필드 활용 가이드

실측한 AI 출력 패턴 기반 권장:

- **리스트 아이템** = `summaryOneLiner` (있을 때) / 없으면 `title`
- **리스트 부제** = `summaryEndDate` 있으면 "D-N 마감" 배지, `summaryType == "action_required"`면 강조
- **상세 상단 카드** = `summary` + `summaryDetails.target/action/host/impact`를 라벨로 렌더
- **기간 표시** = `summaryStartDate ~ summaryEndDate` (+ time 있으면 덧붙이기)
- **원문 버튼** = `sourceUrl`을 외부 브라우저로
- **본문 렌더** = `cleanMarkdown` 네이티브 마크다운 렌더(1순위) → 없으면 `cleanHtml` 웹뷰 fallback → 둘 다 없으면 "본문 준비 중" 또는 `sourceUrl`로 외부 링크.
- **첨부 섹션** = `attachments` 루프, 각 항목 외부 링크

`summaryType`은 AI가 생성하므로 **enum으로 단정 금지**. 실측값(`action_required`, `informational`) 외에도 등장할 수 있음. UI는 default 케이스를 항상 둘 것.

---

## 7. API 설계 시 체크리스트

- [ ] `/notices` 전체 최신순 엔드포인트를 만들 거면 `date_-1` 또는 `crawledAt_-1` 인덱스 추가 필요
- [ ] `/notices?dept=...` 학과별은 기존 `sourceDeptId_1_date_-1` 인덱스로 커버됨
- [ ] `/notices/:deptId/:articleNo` 상세 — 복합키 사용
- [ ] 검색 필요 시 `title`, `contentText`에 text 인덱스 추가 (별도 작업)
- [ ] 기본 필터: `isDeleted: {$ne: true}`, `date >= SERVICE_START_DATE("2026-03-09")`
- [ ] 리스트 응답에서 `content`, `cleanHtml`, `cleanMarkdown` 제외 (크기 큼). `contentText`는 미리보기 길이만큼 자르기
- [ ] 상세 응답에 `cleanMarkdown` projection 포함 (앱 마크다운 렌더 경로용)
- [ ] `category`/`author`가 빈 문자열인 전략(§3 표)을 파악해서 UI 조건부 렌더
- [ ] 요약 없음/stale 상태 표시 정책 결정
- [ ] `sourceUrl` 외부 링크 vs 앱 내 웹뷰 렌더 정책

---

## 8. 핵심 파일 포인터

| 목적 | 경로 |
|---|---|
| Notice 스키마 (dataclass) | `py/src/skkuverse_crawler/notices/models.py:26-49` |
| DB 인덱스 정의 | `py/src/skkuverse_crawler/notices/dedup.py:12-19` |
| 변경 감지 로직 | `py/src/skkuverse_crawler/notices/dedup.py:42-50`, `orchestrator.py` |
| HTML 정제 파이프라인 (6단계) | `py/src/skkuverse_crawler/shared/html_cleaner.py` |
| HTML → Markdown 변환 | `py/src/skkuverse_crawler/shared/html_to_markdown.py` |
| contentText 추출(블록 개행) | `py/src/skkuverse_crawler/notices/normalizer.py:_text_from_clean_html` |
| Backfill 로직 | `py/src/skkuverse_crawler/notices/backfill.py` |
| 요약 프로세서 | `py/src/skkuverse_crawler/notices_summary/processor.py:69-115` |
| 요약 쿼리(pending/stale) | `py/src/skkuverse_crawler/notices_summary/query.py` |
| 학과 config | `departments.json` (레포 루트 SSOT) |
| 전략 구현 | `py/src/skkuverse_crawler/notices/strategies/*.py` |

---

## 9. 검증 방법

이 문서의 데이터 구조가 맞는지 확인하려면:

```bash
# (1) 스키마 정의 재확인
cat py/src/skkuverse_crawler/notices/models.py

# (2) 실제 DB에서 각 전략별 샘플 1건씩 조회
# MCP mongodb find로 skku_notices.notices에 대해 sourceDeptId별로 limit=1
#   sourceDeptId: skku-main, cheme, medicine, dorm-hssc, cal-undergrad, bio-undergrad, nano

# (3) 요약/미요약/stale 상태 카운트
#   요약 완료:  {summaryAt: {$ne: null}}
#   요약 대기:  {contentText: {$ne: null}, summaryAt: null}
#   content 없음: {content: null}
```
