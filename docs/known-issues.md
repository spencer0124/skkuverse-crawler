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

### ~~7. CRAWL_SOURCE_FILTER가 프로덕션에 상주하여 132개 학과 침묵 차단~~ (2026-04-21 해결)
- **문제**: dev/debug용 오버라이드인 `CRAWL_SOURCE_FILTER` env var가 프로덕션 `py/docker-compose.yml`에 하드코딩되어 있어, `sources.json`의 147개 `crawlEnabled: true` 항목 중 **15개만 크롤링**됨. 컨테이너는 `Up 2 days`로 healthy하게 보였으나 실제 coverage는 10.2%.
- **증상**: 24시간 로그에서 동일한 15개 dept_id만 반복 등장, 이외 132개(biz-undergrad, mech-undergrad, cse-undergrad 등 주요 학과 포함)는 시도조차 되지 않음. MongoDB `db.notices.distinct("sourceId")` = 15.
- **해결**: 프로덕션 `py/docker-compose.yml`에서 `- CRAWL_SOURCE_FILTER=...` 라인 삭제 → `docker compose up -d crawler` 재생성. 수동 검증 크롤(`docker exec ... notices --once --source biz-undergrad --pages 1`)에서 11건 신규 수집 확인.
- **재발 방지**: CLAUDE.md의 `CRAWL_SOURCE_FILTER` 설명에 ⚠️ 경고 강화. 향후 "distinct crawled dept count < enabled dept count" 알람 구축 고려.

### ~~8. 법학전문대학원(sls) 사이트 개편으로 게시판 URL 404 → 크롤 침묵 중단~~ (2026-07-29 해결)
- **문제**: sls.skku.edu가 게시판 경로에서 `/community/` 세그먼트를 제거하고 법전원 게시판을 개명(`notice_special_law.do` → `notice_sls.do`). `sls-general`/`sls-special` 두 소스가 2026-07-14경부터 404로 침묵 중단됨.
- **증상**: 매 크롤 틱마다 `list_fetch_failed` 에러 2건 반복, 신규 공지 미수집 약 2주. update-check도 저장된 구 sourceUrl로 전량 404 — 단, **mass-404 안전장치**(총 시도 ≥5건 중 404 비율 >50%면 soft-delete 보류)가 작동해 오삭제 0건.
- **해결**:
  - `sources.json` baseUrl 2건 교체 (`/sls/notice_general_law.do`, `/sls/notice_sls.do`). articleNo 체계가 연속이라 incremental 크롤이 공백 구간을 자동 백필.
  - 기존 문서 200건(sls-general 55 + sls-special 145)의 `sourceUrl`을 새 경로로 일괄 재작성 (구 articleNo가 새 URL에서 정상 렌더됨을 검증 후). `detailPath`는 상대경로(`?mode=view...`)라 무영향.
  - 적대적 검증에서 추가 갭 발견: **`attachments[].url`도 게시판 .do 경로를 내장** (`skku_standard.py`의 `{baseUrl}?mode=download&...`) → 95건(44+51) 추가 마이그레이션. attachNo 체계도 연속이라 새 경로에서 다운로드 정상 (GET 200 검증).
  - **동일 부류**: `success`(학생성공센터)도 같은 개편으로 404 → baseUrl 수정 + sourceUrl 51건/첨부 5건 마이그레이션 (2026-07-29).
- **주의**: sls 다운로드 핸들러는 HEAD 요청에 404/403을 반환하고 GET만 정상 (www.skku.edu는 HEAD 200). `validate-attachments`가 HEAD 기반이라 sls에서 오탐 발생 — GET(range) fallback 개선 여지.
- **재발 방지**: SKKU CMS 개편(`/community/` 경로 제거)이 사이트별 순차 진행 중으로 보임 (sls·success·hakbu 확인, sco는 아직 구경로) — "소스별 연속 list_fetch_failed N틱 이상" 알람 구축 고려 (§7의 coverage 알람과 동일 계열).

### ~~9. 최신 고정 공지가 floor-date early-stop을 무력화하는 잠재 이슈~~ (2026-07-29 해결)
- **문제**: 상단 고정(`공지`) 행은 게시판의 **모든 리스트 페이지에 반복 노출**되는데, floor stop 판정이 `all(item.date < SERVICE_START_DATE)`라 고정글 하나만 서비스 시작일 이후여도 조건이 영원히 거짓 → 새 글이 올라온 틱마다 게시판 끝(또는 max_pages)까지 페이지네이션. 서비스 시작일 이전 일반 글은 저장되지 않아 all_known stop도 발동 불가.
- **증상**: 아직 프로덕션 미발현 (현재 크롤 대상 게시판의 고정글이 전부 2026-03-09 이전). 발현 시 데이터 오염은 없고 list fetch 낭비만 발생하는 잠재 이슈였음.
- **해결**:
  - skku-standard 파서가 첫 info 셀("공지" vs "No.###")로 `NoticeListItem.pinned` 플래그 세팅 (`infoParser: labeled` 게시판은 해당 셀 구조가 없어 기본값 False).
  - floor 판정을 `_page_below_floor()` 순수 함수로 추출, **일반 행만** 대상으로 판정. 고정글만 있는 페이지는 stop하지 않음(페이지 0의 고정글 처리 누락 방지) — 다음 페이지의 empty/all_known이 종료 담당.
  - 같은 뿌리의 실존 비효율도 함께 수정: `dedup.should_continue()`(all-known early-stop)에서도 고정글 제외. floor 이전 고정글은 저장되지 않아 매 페이지가 "미지 항목 있음"으로 보였고, 조용한 틱에도 date floor까지 매번 페이지네이션했음 (sco 기준 list fetch 6회 → 1회). 고정글은 항상 페이지 0에도 노출되므로 제외해도 내용 누락 없음.
  - 테스트 10건 추가 (`test_orchestrator.py::TestPageBelowFloor`, `test_skku_standard.py::test_crawl_list_detects_pinned_rows`, `test_dedup.py::TestShouldContinue`).
- **후속 보강 (같은 날)**:
  - 적대적 검증이 잡은 회귀 창: floor break가 페이지 처리 **전에** 실행되어, "page 0 일반 글 전부 floor 이전 + 신규 고정글" 조합에서 신규 고정글이 영구 누락될 수 있었음 → page 0은 처리 후 break, 깊은 페이지는 처리 전 break (고정글은 page 0에 항상 노출되므로 안전).
  - **구분자 전수 실검증** (2026-07-29): 전 skku-standard 게시판 135개 × 2페이지 = 2,793행 라이브 감사. 첫 info 셀은 예외 없이 "공지" 또는 "No.###" (제3 변형 0건), 파서 pinned 플래그와 셀 값 불일치 0건, 고정글의 페이지 반복 전제 위반 0건, 고정글이 번호행으로 중복 노출된 사례 0건 (고정글 보유 게시판 44개·316행 기준).
- **한계**: pinned 감지는 skku-standard 전략만 구현 (`infoParser: labeled`인 chem은 미적용 — 현재 고정글 0건, 발현 시 성능 저하만). 타 전략(gnuboard 등)의 고정글 관례는 상이하며 동일 증상 발현 시 전략별 감지 추가 필요. `pinned`는 DB에 저장하지 않음(앱 상단 고정 기능은 별도 작업).

### 10. 학부대학(hakbu) 사이트 개편 — 9개 소스 침묵 중단 (미해결, 2026-07-29 발견)
- **문제**: hakbu.skku.edu도 `/community/` 경로 제거 개편(§8과 동일 부류)으로 `hakbu` + `hakbu-portal` 계열 8개가 404. 매 틱 에러 9건.
- **§8보다 복잡한 이유**: 단순 경로 이동이 아님 —
  - 새 게시판(`/hakbu/notice.do`, `/hakbu/notice_total.do`)의 상세 링크가 `articleNo=` 대신 `viewBoardId=...&itemId=...` 체계. itemId가 숫자인 행도 있고 **16진수 문자열인 행도 있음** (`itemId=D7D66C75...`) → 파서의 `articleNo=(\d+)|itemId=(\d+)` 추출 실패로 행 자체가 스킵됨.
  - itemId 숫자부가 기존 articleNo와 다른 번호공간이면 dedup 키 충돌/중복 삽입 + 재푸시 위험.
  - 구 `boardId=13888X` 카테고리 필터가 새 `notice_total.do`에서 유효한지 미확인 (제목은 boardId 무관 동일).
- **필요 작업**: 새 링크 체계 분석 → 파서/전략 대응(16진수 itemId 처리 포함) → 소스 매핑 재설계 → 기존 문서 마이그레이션 전략. 학부통합 계열은 앱 주요 소스라 우선순위 높음.

### 11. cheme·nano SSL 인증서 체인 오류 — 크롤 중단 (미해결, 2026-07-29 발견)
- **문제**: `cheme.skku.edu`/`nano.skku.edu`의 `*.skku.edu` 인증서가 중간 인증서(Thawte TLS RSA CA G1) 없이 서빙됨 (`openssl verify return code: 21 — unable to verify the first certificate`). httpx가 `CERTIFICATE_VERIFY_FAILED`로 매 틱 실패.
- **원인**: 학교 측 인증서 갱신 시 체인 미포함 배포로 추정 (서버 설정 문제).
- **선택지**: (a) 학교 측 수정 대기, (b) 크롤러 fetcher에 해당 중간 CA를 추가한 커스텀 SSL 컨텍스트 (호스트 한정), (c) 해당 소스만 verify 완화 — (c)는 지양.

### 3. `lastModified` 필드 미구현
- 상세 페이지 `<span class="date">최종 수정일 : 2026.03.27</span>` 에서 추출 가능
- 현재는 Notice 모델에 선언만 되어있고 값을 채우지 않음
- Phase 2에서 구현

## Phase 2 계획

### 학과 추가 (같은 skku-standard 유형)
- 5~10개 학과 추가, selectors 차이 확인
- 학과별 baseUrl만 다르고 selector 동일한 경우가 대부분일 것으로 예상
- 다른 경우 sources.json에서 selectors만 오버라이드

### lastModified 파싱
- 상세 페이지에서 `span.date` 텍스트 파싱
- `최종 수정일 : YYYY.MM.DD` 형식 → YYYY-MM-DD로 정규화

### 에러 모니터링
- 파싱 실패율이 높아지면 사이트 구조 변경 감지 알림
- content: null 비율 모니터링
