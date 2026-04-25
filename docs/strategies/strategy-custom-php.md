# Custom-PHP 게시판 크롤링 전략 + 첨부파일 보완 (2026-04-10)

## 개요

`custom-php` 전략은 `cal.skku.edu`(건설환경공학부)처럼 **단일 `index.php` 엔트리포인트 + `?page=list|view` 쿼리 기반** 게시판을 크롤링한다. Gnuboard/SKKU-CMS 어디에도 속하지 않는 자체 제작 PHP 보드다.

| 항목 | 내용 |
|------|------|
| 대상 | `cal-undergrad` (건설환경공학부 학부), `cal-grad` (대학원) |
| 사이트 | https://cal.skku.edu/index.php |
| 리스트 URL | `?hCode=BOARD&bo_idx=17&pg=1&page=list` |
| 상세 URL | `?hCode=BOARD&bo_idx=17&page=view&idx={articleNo}` |
| 페이지네이션 | pageNum (`pg=1,2,3...`), 페이지당 15건 |
| articleNo 추출 | 제목 링크 `href`의 `idx=(\d+)` 정규식 |

---

## 첨부파일 미수집 문제 (해결)

### 배경

초기 구현에서 `custom_php.py:93` (`crawl_detail`)이 **항상 `attachments=[]`를 반환**하고 있었다. 결과적으로 건설환경공학부 학부/대학원 두 학과의 첨부파일이 전혀 수집되지 않았다 — 학사 공고에는 신청서·이수계획서 양식이 많아 사용자 입장에서 체감 손실이 컸다.

실측 (조사 시점, `skku_notices_dev`):
- 전체 문서 284건, `sourceUrl` 100% 건강
- 첨부 보유 30건(10.6%) — 모두 skku-standard 계열, cal 학과는 0건

### DOM 구조 분석 (cal.skku.edu)

상세 페이지 본문 하단에 **토글형 첨부 래퍼** `div.attachment`가 있고, 내부 앵커가 NFUpload 다운로더를 가리킨다:

```html
<div class="attachment">
  <a href="./NFUpload/nfupload_down.php?tmp_name=1938920257_abcf35e8.jpg&name=%EB%8C%80%ED%95%9C%ED%86%A0%EB%AA%A9%ED%95%99%ED%9A%8C.jpg">
    내 pc저장
  </a>
</div>
```

중요 관찰: **링크 텍스트는 "내 pc저장"(다운로드 버튼 라벨)이고 실제 파일명은 `name=` 쿼리 파라미터에 URL-인코딩되어 있다.** 이를 파악하지 못하면 파일명이 "내 pc저장"으로 저장되는 UX 오류가 발생한다.

href 경로는 `./NFUpload/...` 상대 경로인데, `baseUrl`이 `.../index.php` **파일**이어서 `urljoin()`으로는 원하는 결과가 나오지 않을 수 있다 → `index.php`의 **부모 디렉터리**를 기준으로 명시 처리.

### 구현 결정

1. **셀렉터는 config 중심** — `sources.json`에 `detailAttachment` 키를 추가하고 코드는 `.get("detailAttachment", "div.attachment a[href]")`로 기본값만 보장. gnuboard / gnuboard-custom가 따르는 관례와 일치.
2. **파일명 추출 우선순위**: `name=` 쿼리 파라미터 → 링크 텍스트 → URL basename. `nfupload_down.php` 외 일반 상대 경로 첨부(`./files/plain.pdf` 등)에도 동작하도록 폴백 체인 설계.
3. **URL 절대화**: `./` / `/` / `http` / 그 외(상대)를 분기 처리. 기준 디렉터리는 `baseUrl.rsplit("/", 1)[0]` (= `https://cal.skku.edu`).
4. **중복 URL 제거** — 같은 첨부가 여러 번 노출될 수 있어 `seen_urls` 세트로 디둡.

### 구현 (최종 반영)

`py/src/skkuverse_crawler/notices/strategies/custom_php.py`, `crawl_detail()` 내부:

```python
from urllib.parse import parse_qs, quote, unquote, urlparse

# ...
attachments: list[dict[str, str]] = []
attachment_selector = config.get("selectors", {}).get(
    "detailAttachment", "div.attachment a[href]"
)
parsed = urlparse(config["baseUrl"])
origin = f"{parsed.scheme}://{parsed.netloc}"
base_dir = config["baseUrl"].rsplit("/", 1)[0]

seen_urls: set[str] = set()
for a in soup.select(attachment_selector):
    href = a.get("href", "")
    if isinstance(href, list):
        href = href[0]
    if not href or href == "#":
        continue
    if href.startswith("http"):
        full_url = href
    elif href.startswith("./"):
        full_url = f"{base_dir}/{href[2:]}"
    elif href.startswith("/"):
        full_url = f"{origin}{href}"
    else:
        full_url = f"{base_dir}/{href}"

    qs = parse_qs(urlparse(full_url).query)
    name_param = qs.get("name", [""])[0]
    if name_param:
        name = unquote(name_param).replace("+", " ")
    else:
        name = a.get_text(strip=True) or full_url.rsplit("/", 1)[-1]
    if not name:
        continue

    if full_url in seen_urls:
        continue
    seen_urls.add(full_url)
    attachments.append({"name": name, "url": full_url})
```

`sources.json` (양쪽 cal 엔트리):

```json
"selectors": {
  ...,
  "detailContent": "div.board_content",
  "detailAttachment": "div.attachment a[href]"
}
```

### 라이브 검증 결과

네트워크 경유 실 크롤 (MongoDB 미사용 ad-hoc 스크립트):

```
[LIST] 213 items
  articleNo=1309  title='2026 제29회 토목의날 행사'  attachments=1
    - 대한토목학회.jpg  →  https://cal.skku.edu/NFUpload/nfupload_down.php?...&name=...
  articleNo=1299  title='2026학년도 건설환경공학부 교육과정 로드맵'  attachments=2
    - 2026학년도 학과별 교육과정 로드맵_건축공학심화.pdf  →  https://.../nfupload_down.php?...
    - 2026학년도 학과별 교육과정 로드맵_토목공학심화.pdf  →  https://.../nfupload_down.php?...

[SUMMARY] 2/10 articles had attachments
```

- 파일명이 한글/공백/특수문자 포함 원본 그대로 정상 복원됨(`+` → 공백, URL-decode 완료).
- 절대 URL이 `https://cal.skku.edu/NFUpload/...` 형태로 올바르게 조립됨.
- 첨부 없는 글은 빈 리스트 반환(회귀 없음).

### 놓인 리스크 / 비적용 항목

- **파일 자체는 다운로드하지 않음** — URL 저장만. 서버가 `tmp_name` 토큰을 만료시키면 링크가 죽을 수 있다. 아카이빙 레이어는 별도 인프라 의사결정.
- **파일명 정규화** — 현재는 원본 그대로 보존(사람이 쓴 파일명이 UX에 가장 적합). 특수문자로 인한 실 장애 사례 없음.

---

## 연관 보완: wordpress-api 첨부 확장자 화이트리스트 확장

같은 사이클에서 `wordpress_api.py`의 확장자 정규식이 **문서 형식만** 포함(`pdf|hwp|office|zip|rar|7z`)해 이미지·텍스트·미디어 다운로드 링크를 놓칠 위험이 확인되었다.

### 변경

`py/src/skkuverse_crawler/notices/strategies/wordpress_api.py`:

```python
FILE_EXTENSIONS = re.compile(
    r"\.(pdf|hwp|hwpx|xlsx|xls|docx|doc|pptx|ppt|zip|rar|7z"
    r"|txt|csv|tsv|rtf|xml|json"
    r"|jpg|jpeg|png|gif|webp|bmp|tiff|svg"
    r"|mp3|mp4|mov|avi|mkv|wav)$",
    re.I,
)
UPLOADS_PATH = re.compile(r"/wp-content/uploads/", re.I)

# _extract_attachments:
if href and (FILE_EXTENSIONS.search(href) or UPLOADS_PATH.search(href)):
```

### 결정 근거

- **경로 기반(`/wp-content/uploads/`) 보강**이 확장자 기반보다 견고 — 프리뷰 URL, 쿼리 파라미터가 붙은 경우도 포착.
- `OR` 조합으로 누락 최소화 (인라인 이미지 링크가 포함될 수 있으나, 그 경우는 사용자가 "다운로드 가능 링크"로 의도한 케이스라 UX상 허용).
- 모델 필드는 `list[{name, url}]` URL 리스트일 뿐, "첨부 vs 인라인 이미지" 분기는 소비자(프론트) 몫.

### 회귀 테스트

- 기존 pdf/hwp 포착 정상
- `/wp-content/uploads/**/*.jpg` 포착
- 일반 페이지 링크(`/about`, `/category/notice`)는 무시
- 확장된 미디어(`.txt`, `.mp4`) 포착

---

## 테스트 커버리지

`py/tests/notices/strategies/` (신규):

| 파일 | 케이스 수 | 내용 |
|------|----------|------|
| `test_custom_php.py` | 4 | `name=` 파라미터 우선 / 링크 텍스트 폴백 / 첨부 없음 / 절대 URL 보존 |
| `test_wordpress_api.py` | 4 | uploads 경로 / 기존 doc 회귀 / 일반 링크 제외 / 확장 미디어 |

**최종 상태**: 전체 테스트 **105 passed**, `ruff check` / `mypy` 클린.

---

## 영향받은 파일

| 파일 | 변경 |
|------|------|
| `py/src/skkuverse_crawler/notices/strategies/custom_php.py` | `urlparse/parse_qs/unquote` import, `crawl_detail` 내 첨부 추출 로직 구현 |
| `py/src/skkuverse_crawler/notices/strategies/wordpress_api.py` | `FILE_EXTENSIONS` 확장 + `UPLOADS_PATH` 보강 |
| `py/src/skkuverse_crawler/notices/config/sources.json` | `cal-undergrad`, `cal-grad` 엔트리에 `detailAttachment` 셀렉터 추가 |
| `py/tests/notices/strategies/test_custom_php.py` | 신규, 4 케이스 |
| `py/tests/notices/strategies/test_wordpress_api.py` | 신규, 4 케이스 |

## 남은 E2E 검증 (사용자 실행 권장)

전략 로직은 라이브 검증 완료. MongoDB 적재 검증은 로컬 환경변수 설정 후:

```bash
cd py
python -m skkuverse_crawler notices --once --source cal-undergrad --pages 1
# MongoDB (skku_notices_dev.notices)에서 dept 필터 + attachments.0 존재 확인
```
