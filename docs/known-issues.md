# Known Issues & Phase 2 TODO

## Known Issues (1단계)

### 1. ~~Incremental crawl에서 1페이지 상세 fetch를 매번 수행~~ (해결됨)
- **해결**: `findExistingMeta()`로 DB의 title/date와 비교, 변경된 글만 상세 fetch
- **변경 없는 글**: `touchNotice()`로 views + crawledAt만 갱신 (상세 fetch 생략)
- **효과**: 변경 없을 시 목록 1회 + DB 쿼리 1회로 끝남 (5.1초 → 0.4초)

### 2. 첨부파일이 없는 글이 대다수
- 첨부 아이콘이 있어도 `filedown_list`가 비어있는 경우 존재
- 일부 글은 이미지를 본문에 인라인으로 포함 (첨부파일로 잡히지 않음)
- 현재는 `filedown_list li a` 셀렉터로 실제 다운로드 링크만 수집 → 검증 완료

### ~~4. custom-php / wordpress-api 전략의 첨부파일 누락~~ (2026-04-10 해결)
- **custom-php** (`cal-undergrad`, `cal-grad`): `crawl_detail`이 항상 `attachments=[]` 반환 → 건설환경공학부 양 과정의 첨부파일이 전혀 수집되지 않았음
- **wordpress-api**: 확장자 화이트리스트가 문서 형식만 포함(pdf/hwp/office/zip) → 이미지·텍스트·미디어 다운로드 누락 가능
- **해결**:
  - custom-php에 `div.attachment a[href]` 기반 추출 로직 추가. 파일명은 `nfupload_down.php?name=...` 쿼리 파라미터를 URL-decode하여 복원(링크 텍스트 "내 pc저장"은 다운로드 버튼 라벨이라 부적절).
  - wordpress-api의 `FILE_EXTENSIONS`에 이미지/텍스트/미디어 확장자 확장 + `/wp-content/uploads/` 경로 기반 보강(OR 조합).
  - `cal.skku.edu` 라이브 검증: 10건 중 2건에서 한글 파일명(`대한토목학회.jpg`, `2026학년도 학과별 교육과정 로드맵_건축공학심화.pdf` 등) 정상 추출 확인.
- **상세**: `docs/strategies/strategy-custom-php.md` 참조.

### ~~5. wordpress-api WPDM 첨부파일 랜딩 페이지 URL~~ (2026-04-18 해결)
- **문제**: cheme의 WPDM(WordPress Download Manager) 첨부파일이 `/download/{slug}/` 랜딩 페이지 URL로 저장되어 실제 파일 다운로드 불가
- **원인**: `WPDM_DOWNLOAD` 정규식이 `<a href>` 의 랜딩 페이지 URL을 캐치. 실제 다운로드 URL은 `<a data-downloadurl=".../?wpdmdl={id}&refresh={hash}">` 속성에 존재
- **해결**:
  - `WPDM_DOWNLOAD` 정규식 제거, `div.w3eden` 컨테이너 단위로 `data-downloadurl` 추출
  - 일시적 `refresh` 토큰 제거, `?wpdmdl={id}`만 저장 (검증: refresh 없이 다운로드 작동)
  - 파일명은 `h3.package-title a` 텍스트에서 추출
  - `html_cleaner.py`의 `REMOVE_SELECTORS`에 `div.w3eden` 추가 → cleanHtml/cleanMarkdown에서 WPDM UI 블록 제거
  - `backfill-wpdm-attachments` CLI 명령어로 기존 DB 문서 수정 지원

### ~~6. 리스트 페이지 byte-truncation으로 인한 false-positive 변경 감지~~ (2026-04-21 해결)
- **문제**: `cal.skku.edu` 등 일부 소스가 list page의 title을 byte 경계로 잘라서, UTF-8 다바이트 문자(예: `공`, 3-byte) 중간이 끊겨 trailing U+FFFD(`�`) replacement character가 `...` 직전에 들어감. `dedup.has_changed()`의 ellipsis-prefix 방어 로직이 `�`를 prefix 끝에 포함시켜 DB에 저장된 정상 title과 startswith 매칭 실패 → 변경됨으로 오판.
- **증상**: `cal-undergrad`의 고정 공지(articleNo 1317)가 매 cycle마다 list의 모든 페이지에서 `change_detected`로 반복 감지 → detail 재fetch + editHistory push. cycle당 `cal-undergrad` 혼자 약 100초 소요, editHistory `$slice: -20` 덕분에 무한 증가는 방지됐으나 매 cycle 20건씩 가짜 entry 누적.
- **해결**: `dedup.has_changed()`에서 prefix를 `rstrip("�")` 후 비교. post-strip prefix가 비어있을 때는 과매칭 방지 guard 추가. 테스트 7건 추가(`tests/notices/test_dedup.py::TestHasChanged`).
- **상세**: `py/src/skkuverse_crawler/notices/dedup.py`, PR #19

### ~~7. CRAWL_DEPT_FILTER가 프로덕션에 상주하여 132개 학과 침묵 차단~~ (2026-04-21 해결)
- **문제**: dev/debug용 오버라이드인 `CRAWL_DEPT_FILTER` env var가 프로덕션 `py/docker-compose.yml`에 하드코딩되어 있어, `departments.json`의 147개 `crawlEnabled: true` 항목 중 **15개만 크롤링**됨. 컨테이너는 `Up 2 days`로 healthy하게 보였으나 실제 coverage는 10.2%.
- **증상**: 24시간 로그에서 동일한 15개 dept_id만 반복 등장, 이외 132개(biz-undergrad, mech-undergrad, cse-undergrad 등 주요 학과 포함)는 시도조차 되지 않음. MongoDB `db.notices.distinct("sourceDeptId")` = 15.
- **해결**: 프로덕션 `py/docker-compose.yml`에서 `- CRAWL_DEPT_FILTER=...` 라인 삭제 → `docker compose up -d crawler` 재생성. 수동 검증 크롤(`docker exec ... notices --once --dept biz-undergrad --pages 1`)에서 11건 신규 수집 확인.
- **재발 방지**: CLAUDE.md의 `CRAWL_DEPT_FILTER` 설명에 ⚠️ 경고 강화. 향후 "distinct crawled dept count < enabled dept count" 알람 구축 고려.

### 3. `lastModified` 필드 미구현
- 상세 페이지 `<span class="date">최종 수정일 : 2026.03.27</span>` 에서 추출 가능
- 현재는 Notice 모델에 선언만 되어있고 값을 채우지 않음
- Phase 2에서 구현

## Phase 2 계획

### 학과 추가 (같은 skku-standard 유형)
- 5~10개 학과 추가, selectors 차이 확인
- 학과별 baseUrl만 다르고 selector 동일한 경우가 대부분일 것으로 예상
- 다른 경우 departments.json에서 selectors만 오버라이드

### lastModified 파싱
- 상세 페이지에서 `span.date` 텍스트 파싱
- `최종 수정일 : YYYY.MM.DD` 형식 → YYYY-MM-DD로 정규화

### 에러 모니터링
- 파싱 실패율이 높아지면 사이트 구조 변경 감지 알림
- content: null 비율 모니터링
