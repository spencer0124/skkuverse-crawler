# Crawl Flow Guide

성균관대학교 각 학과/부서의 공지사항을 자동으로 수집해서 MongoDB에 저장하는 크롤러의 동작 흐름을 단계별로 설명한다.

> 코드 구조와 설정 레퍼런스는 [architecture.md](./architecture.md) 참조.

---

## 1단계: 시작 — 스케줄러

```
python -m skkuverse_crawler start
```

`cli.py`의 `start()` → `_start_scheduler()`가 실행되면 **3개의 모듈**을 등록한다:

| 모듈 | 역할 | 주기 |
|------|------|------|
| NoticesModule | 공지 크롤링 | 30분마다 |
| NoticesUpdateCheckModule | 기존 공지 변경 감지 | 하루 3번 (08:10, 14:10, 20:10) |
| NoticesSummaryModule | AI 요약 생성 | 매시 20분 |

APScheduler가 각 모듈의 `cron_schedule`에 따라 `mod.run()`을 자동 호출한다.

- `max_instances=1` + `coalesce=True` — 이전 크롤링이 안 끝났으면 중복 실행 없이 건너뜀 (서버 과부하 방지)
- `misfire_grace_time=10` — 스케줄 시간을 10초 이상 놓치면 건너뜀

---

## 2단계: 크롤링 시작 — Orchestrator

`NoticesModule.run()`이 호출되면:

```python
departments = load_and_validate()   # sources.json에서 학과 목록 로드
results = await run_crawl(departments, options)
```

`sources.json`에는 크롤링할 학과들이 정의돼 있다. 각 학과마다 "어떤 웹사이트 구조인지" 전략(strategy)이 지정돼 있다.

`run_crawl()` (orchestrator.py)이 하는 일:

1. MongoDB 연결 + 인덱스 보장
2. `Semaphore(5)` — **동시에 최대 5개 학과만 병렬 크롤링**
3. 각 학과별로 `_crawl_department()` 호출

---

## 3단계: 학과 하나를 크롤링하는 과정

`_crawl_department()`가 크롤러의 핵심이다.

### 3-1. null content 재크롤링 (복구)

```python
null_refs = await find_null_content(collection, dept["id"])
```

이전에 크롤링했는데 본문을 못 가져온(content가 null인) 공지가 있으면, 먼저 그것들의 상세 페이지를 다시 시도한다. 네트워크 에러 등으로 실패한 글을 복구하는 단계.

### 3-2. 목록 페이지 순회 (메인 루프)

```python
while page < max_pages:
    list_items = await strategy.crawl_list(dept, page)
```

학과 공지 웹사이트의 **목록 페이지**를 1페이지, 2페이지, 3페이지... 순서로 가져온다. 각 페이지에는 공지 10~20개의 제목, 날짜, 글번호 같은 메타정보가 있다.

#### Strategy Pattern — 학과별 파싱 전략

성균관대는 학과마다 웹사이트 구조가 다르다:

| 전략 | 대상 |
|------|------|
| `skku-standard` | 성대 표준 게시판 (대부분) |
| `skkumed-asp` | 의대 (ASP 기반) |
| `wordpress-api` | 워드프레스 사용 학과 |
| `jsp-dorm` | 기숙사 (JSP) |
| `custom-php` | 커스텀 PHP 게시판 |
| `gnuboard` | Gnuboard 기반 |
| `gnuboard-custom` | Gnuboard 커스텀 변형 |

`STRATEGY_MAP`이 `sources.json`의 `"strategy"` 문자열을 실제 클래스로 매핑한다. 새 학과를 추가할 때 기존 전략이 맞으면 JSON에 한 줄만 추가하면 되고, 구조가 다르면 새 Strategy 클래스만 만들면 된다.

### 3-3. Incremental 크롤링 — 똑똑하게 건너뛰기

매번 전체 공지를 다 가져오면 낭비이므로, **변경분만 가져오는** 최적화 로직:

```python
existing_meta = await find_existing_meta(collection, dept["id"], article_nos)
all_known = not should_continue(list_items, existing_meta)
```

1. 목록 페이지의 글번호들을 DB에서 찾아본다
2. 전부 이미 DB에 있으면 → `all_known = True`

판단 기준:

```
[1페이지] 새 글 2개 + 기존 8개 → 새 글 크롤링, 다음 페이지로
[2페이지] 전부 기존 글 → STOP! 더 볼 필요 없음
```

- 1페이지인데 전부 아는 글이면 → 변경 체크만 하고 바로 종료 (새 공지 없음)
- 2페이지 이후인데 전부 아는 글이면 → 즉시 종료 (더 뒤로 갈 필요 없음)
- 모르는 게 있으면 → 상세 페이지 크롤링 계속

#### 변경 감지 (`has_changed`)

기존 글의 **제목**이나 **날짜**가 바뀌었으면 "변경됨"으로 판단한다. 단, 목록 페이지에서 제목이 `...`으로 잘려있는 경우를 고려해서, `"성균관대학교 2026년..."` 같이 잘린 제목은 DB의 전체 제목 앞부분과 비교하여 오탐을 방지한다.

### 3-4. 상세 페이지 크롤링 + 정규화

새 공지이거나 변경된 공지를 발견하면:

```python
detail = await strategy.crawl_detail(ref, dept)    # HTML 가져오기
notice = build_notice(item, detail, ...)            # 5가지 출력 생성
```

`build_notice()`에서 하나의 공지가 **4가지 형태**로 변환된다:

```
원본 HTML (학교 웹페이지)
    ↓ clean_html()             → cleanHtml      (정리된 HTML)
    ↓ _text_from_clean_html()  → contentText     (순수 텍스트)
    ↓ html_to_markdown()       → cleanMarkdown   (마크다운)
    ↓ normalize_content_urls() → content          (URL 절대경로화한 원본)
    ↓ compute_content_hash()   → contentHash      (변경 감지용 해시)
```

| 필드 | 용도 |
|------|------|
| `content` | 원본 HTML (URL 절대경로화) — 모바일 앱 HTML 렌더링용 |
| `cleanHtml` | 정리된 HTML — 후속 처리(텍스트 추출, 마크다운 변환)의 기준 |
| `contentText` | 순수 텍스트 — 검색, AI 요약용 |
| `cleanMarkdown` | 마크다운 — 깔끔한 텍스트 표시용 |
| `contentHash` | 본문 해시값 — 다음 크롤링 때 변경 여부 빠르게 비교 |

크롤링 시점에 한 번만 변환해두면 소비자(앱, 검색, AI)가 읽을 때마다 매번 변환하지 않아도 된다.

### 3-5. DB 저장

| 상황 | 동작 |
|------|------|
| 새 공지 | `upsert_notice()` — `articleNo + sourceId` 기준 insert |
| 변경된 공지 | `update_with_history()` — 본문 업데이트 + `editHistory` 배열에 변경 이력 기록 (최대 20건) |
| 변경 없는 공지 | `bulk_touch_notices()` — 조회수(`views`)와 `crawledAt`만 갱신 |

---

## 전체 흐름 다이어그램

```
[30분마다 스케줄러 트리거]
    │
    ▼
run_crawl(departments)
    │
    ├── 학과 A ──┐
    ├── 학과 B ──┤  (최대 5개 병렬, Semaphore)
    ├── 학과 C ──┘
    │
    ▼ (각 학과별)
_crawl_department()
    │
    ├── 1. content=null인 이전 실패 공지 복구
    │
    ├── 2. 목록 1페이지 가져오기 (strategy.crawl_list)
    │   ├── DB와 비교 → 전부 아는 글이면 STOP
    │   └── 새/변경 글 발견 → 상세 크롤링
    │
    ├── 3. 목록 2페이지, 3페이지... (새 글 없을 때까지)
    │
    └── 4. 각 공지:
        ├── strategy.crawl_detail() → HTML 가져오기
        ├── build_notice() → 5가지 출력 생성
        └── upsert/update → MongoDB 저장
```
