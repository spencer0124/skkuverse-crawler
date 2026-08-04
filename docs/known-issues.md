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
  - `backfill-wpdm-attachments` CLI 명령어로 기존 DB 문서 수정 지원 *(당시. 이 커맨드는 adr-006 리팩터에서 삭제됐다 — [cli-usage.md](cli-usage.md) §없어진 커맨드)*

### ~~6. 리스트 페이지 byte-truncation으로 인한 false-positive 변경 감지~~ (2026-04-21 해결)
- **문제**: `cal.skku.edu` 등 일부 소스가 list page의 title을 byte 경계로 잘라서, UTF-8 다바이트 문자(예: `공`, 3-byte) 중간이 끊겨 trailing U+FFFD(`�`) replacement character가 `...` 직전에 들어감. `dedup.has_changed()`의 ellipsis-prefix 방어 로직이 `�`를 prefix 끝에 포함시켜 DB에 저장된 정상 title과 startswith 매칭 실패 → 변경됨으로 오판.
- **증상**: `cal-undergrad`의 고정 공지(articleNo 1317)가 매 cycle마다 list의 모든 페이지에서 `change_detected`로 반복 감지 → detail 재fetch + editHistory push. cycle당 `cal-undergrad` 혼자 약 100초 소요, editHistory `$slice: -20` 덕분에 무한 증가는 방지됐으나 매 cycle 20건씩 가짜 entry 누적.
- **해결**: `dedup.has_changed()`에서 prefix를 `rstrip("�")` 후 비교. post-strip prefix가 비어있을 때는 과매칭 방지 guard 추가. 테스트 7건 추가(`tests/notices/test_dedup.py::TestHasChanged`).
- **상세**: PR #19. 당시 파일은 `notices/dedup.py`, 현재는 `modules/notices/policy.py::has_changed` (adr-006 PR 5에서 순수 술어와 저장 로직이 갈렸다)

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
- **재발 방지**: SKKU CMS 개편(`/community/` 경로 제거)이 사이트별 순차 진행 중으로 보임 (sls·success·hakbu 확인 — hakbu는 §10에서 해결, sco는 아직 구경로) → **crawl_health 알림 시스템 구축됨** (2026-07-29, `docs/architecture.md` "Crawl Health" 참조): 소스가 연속 3틱 page-0 실패 시 Discord 알림 + 매일 09:00 요약. 다음 개편은 1.5시간 내 감지.

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

### ~~10. 학부대학(hakbu) 사이트 개편 — 9개 소스 침묵 중단~~ (2026-07-29 해결, [adr-005](decisions/adr-005-hakbu-board-remap.md))
- **문제**: hakbu.skku.edu도 `/community/` 경로 제거 개편(§8과 동일 부류)으로 `hakbu` + `hakbu-portal` 계열 8개가 404. 매 틱 에러 9건. crawl_health 알림(연속 3틱 실패)으로 감지 — §8 재발 방지 체계의 첫 실전 작동.
- **조사 결과** (라이브 검증):
  - 새 게시판: `/hakbu/notice.do`(나브 "공지사항") · `/hakbu/notice_total.do`(나브 "통합공지"). 리스트·첨부 셀렉터 전부 호환, 상세 content는 §8 부류와 동일하게 코드 fallback(`div.board-view-content-wrap`)이 처리.
  - 구 `boardId=138880~138886` 필터는 새 `notice_total.do`에서 **그대로 유효** (실검증: `?boardId=138880` 시 해당 보드 글만 반환. 신규 138879=학사 보드도 존재하나 미사용).
  - 상세 링크는 `viewBoardId=...&itemId=...` 체계. **hex UNID는 전량 2025-05 이전 레거시 글** (구 시스템 마이그레이션 잔재) — 최신 글은 숫자 itemId만 사용.
  - 기존 파서 `itemId=(\d+)`는 숫자로 시작하는 hex(`itemId=75E2...` → `75`)에서 **잘못된 articleNo를 추출**하는 버그 보유 — 새 보드 크롤 전 필수 수정 대상이었음.
  - dedup/마이그레이션 우려는 해소: prod DB에 hakbu 계열 문서 **0건** (§7 필터 인시던트와 개편 시점이 겹쳐 한 번도 성공 적재된 적 없음) → 충돌할 기존 데이터 자체가 없음.
- **해결**:
  - `hakbu`만 baseUrl 리맵 (`→ /hakbu/notice.do`, name "학부대학(계열제)" 유지). **`hakbu-portal` + 슬라이스 7개는 sources.json에서 삭제** — 콘텐츠 실측(2026-07-30) 결과 통합공지는 대학 포털 공지의 신디케이션 미러로, 동일 글이 이미 `skku-main`/`skku-notice02~07`에 크롤되고 있음을 DB 대조로 확인 (입학·장학 슬라이스는 현행 글 2~3건뿐인 휴면 상태). 근거·재검토 조건은 [adr-005](decisions/adr-005-hakbu-board-remap.md).
  - `skku_standard.py` ID 추출에 negative lookahead 추가 (`articleNo|itemId=(\d+)(?![0-9A-Za-z])`) — hex 부분 매칭 오추출 차단. hex UNID 행은 의도적 skip + debug 로그(`legacy_unid_item_skipped`, warning 스팸 방지).
  - 테스트 3건 추가 (`test_skku_standard.py::test_hakbu_*`): 숫자 itemId 추출, hex skip(75 오추출 방지 명시), boardId 쿼리 조립.
- **주의**: 첫 성공 틱이 빈 DB 기준 자동 백필 (incremental max 100페이지, all-hex 레거시 페이지에서 자연 종료). 첨부 URL은 `portal.skku.edu/...downloadFile.do` 절대 URL — ALLOWED_HOST suffix(`skku.edu`) 통과 확인.

### ~~11. cheme·nano SSL 인증서 체인 오류 — 크롤 중단~~ (2026-07-29 소스 제외로 종결, 재활성 조건부)
- **문제**: `cheme.skku.edu`/`nano.skku.edu`의 `*.skku.edu` 인증서(notBefore 2026-07-16, 서버 배포 07-21)가 중간 인증서(Thawte TLS RSA CA G1) 없이 서빙됨 (`openssl verify return code: 21`). httpx가 `CERTIFICATE_VERIFY_FAILED`로 매 틱 실패, 마지막 성공 둘 다 07-21 14:33 KST.
- **조사 결과**:
  - nano: certifi + 중간 CA 보충 컨텍스트로 핸드셰이크·크롤 엔드포인트 200 실증 — SSL만의 문제.
  - cheme: SSL 통과 후에도 **Cloudflare 봇 챌린지 403** ("Just a moment...") — wp-json·RSS(`/feed/` 등)·루트 전 경로, 로컬·oracle VM IP 모두 동일. 챌린지 우회는 만들지 않음(정책).
- **결정 (2026-07-29, 운영자)**: 크롤러 측 인증서 보충/우회 없이 **소스 제외로 처리**. `sources.json`에서 두 소스 `crawlAvailable: false` + `excludeReason: "temporarilyUnavailable"`(앱 노출: "잠시 점검 중이에요" + 공과대학 우산 대안 제안) + 기술 사유는 내부 전용 `excludeNote` 필드(ssl / ssl+cloudflare)에 기록.
- **재활성 조건**: nano — `openssl s_client`로 체인 정상 서빙 확인 시 플래그 원복만 하면 됨. cheme — 챌린지 해제 확인 시. 재활성 후 백필분은 푸시 억제 절차(**§13**) 필요.
- **파생 수정**: 제외된 소스의 stale crawl_health 상태가 일일 요약을 영구 오염하는 문제 → 요약이 enabled 소스로 필터하도록 수정 (당시 `crawl_health/module.py`, 현재 `plugins/health/module.py`).

### ~~12. 첨부 4종 동시 파손 — 그리고 검증기가 넷 다 정상으로 보고하던 이유~~ (2026-08-04 해결)

- **탐지 구멍이 본체다**: 파손된 다운로드 엔드포인트는 404를 주지 않는다. **HTTP 200 + `text/html`**로 JavaScript alert 페이지를 준다 — cal은 `alert("Access denied!!")`(110B), dorm은 "다운로드 받으실 파일이 존재하지 않습니다"(327B), bio는 `오류안내 페이지`. `check_reachability`가 `status >= 400`만 봤으므로 **넷 다 정상으로 보고돼 왔다**. HEAD → ranged GET으로 바꾸고 `html_response` 체크를 추가 (Content-Type이 `text/html`이면서 `Content-Disposition: attachment`가 없으면 파손). 부수 효과로 §8의 **sls HEAD 오탐도 해소** — sls는 HEAD에 404/403, GET에만 정상.

- **(a) cal 첨부 101건 전량 사망** — NFUpload가 `Referer` 헤더를 검증하는데 `custom_php.py`가 `{name, url}`만 저장. 서버 프록시는 저장된 `referer`가 있을 때만 헤더를 실어 보내므로(`notices.controller.ts:397`) 보낼 것이 없었다. 실증: Referer만 → 407KB PDF / 쿠키만 → Access denied 110B. gnuboard와 같은 형태로 `referer` 저장 + `REFERER_REQUIRED_STRATEGIES` 신설.
  - ⚠️ `GNUBOARD_STRATEGIES`와 **별도 상수로 유지**해야 한다. gnuboard는 세션 게이트라 HTTP 체크를 *스킵*하지만, cal은 referer만으로 충분하므로 체크를 *받아야* 한다. 한 상수로 합치면 cal이 검증 사각지대로 들어간다.

- **(b) dorm `attach_no`가 안정적 ID가 아님** — 글 수정 시 재발급된다. 87776은 저장 `7470` → 실제 `7473`. 더 나쁜 건 **87829의 `7472`**: 저장명은 "2026 Fall Semester Dormitory Admission Guidance.pdf"인데 서버는 `Guidance_for_Paying_dormitory_fee.pdf`를 서빙했다(md5 대조 확인). **오류 없이 다른 문서가 다운로드되는** 상태. 구조적 원인은 Tier-2가 `attachments`를 갱신하지 않던 것([follow-ups.md](follow-ups.md) §5-c) → `ContentFields.as_set(attachments=...)`로 크롤·Tier-2가 같은 필드 정의를 지나가게 수정.
  - 단, Tier-2는 **content hash가 움직일 때만** 쓴다. 파일만 교체된 글은 여전히 안 잡히므로 `repair-attachments`가 필요하다.

- **(c) chem 공지 0건 (영구), 경고 470건/일** — `sources.json`에 `"category": ""`. soupsieve가 빈 셀렉터를 `Expected a selector at position 0`으로 거부하는데, 그 raise가 파서의 **행 단위 try 안**에서 터져 10행이 전부 조용히 삼켜지고 `empty_list_page`가 됐다. 3계층 수정: 파서가 `category`를 optional로(`selectors.get`), 로더가 **빈 문자열 셀렉터를 기동 시점에 거부**, `parse_list_item_failed` 로그에 `dept_id` 추가(이게 없어서 470건이 추적 불가능했다). `REQUIRED_SELECTORS["skku-standard"]`에서 `category` 제거 — 카테고리 컬럼 없는 게시판은 정당하다.
  - **테스트가 못 잡은 이유**: `ONCLICK_CONFIG` 픽스처가 `"category": ""`를 그대로 들고 있었지만 `crawl_detail`에만 쓰여 `crawl_list`를 한 번도 통과하지 않았다.
  - chem은 유일한 `attachmentParser: "onclick"` 소스 — 이 수정으로 **해당 경로가 프로덕션에서 처음 실행**됐고, 첨부 추출 정상 확인 (295KB PDF).

- **(d) support 공지 57건 전부 `contentText: null`** — 상세 페이지가 portal 로그인 폼을 반환(HTTP 200 + 로그인 HTML). null-content 자동 재크롤 루프가 하루 51회(`detail_fetch_failed` 25 + `non_retryable_error` 26) 영구 재시도 중이었다. `crawlEnabled/crawlAvailable: false` + `excludeReason: "loginRequired"`로 제외. 기존 57건은 삭제하지 않음(소스 제외로 앱 미노출).

- **(e) 세 번째 실패 유형 — 원본이 파일을 지운 경우**: cal-grad 1353은 상세 페이지에 첨부 링크가 0개인데 저장된 URL만 남아 있었다. offline 수리로는 보이지 않고 Tier-2도 못 잡는다(파일 삭제는 본문 해시를 움직이지 않는다). `repair-attachments --refetch`로 처리.

- **수리 결과 (프로덕션)**: cal 63건(첨부 101) + dorm 5건 + cal-grad 1건. 검증 재실행 시 **issues 66건 → 0건**. 재실행 멱등 확인(scanned 76, repaired 0).

- **버그가 아니라고 확인한 것**: `ccrf`/`comedu-grad`/`sco-culture` 공지 0건은 최신글이 각각 2026-01-16 / 2026-03-06 / 2025-09-05로 전부 `SERVICE_START_DATE`(2026-03-09) 미만 — floor 로직 정상. `health`/`larc`/`gbme-grad` 첨부 0%는 실제로 첨부 없는 글. `pharm`/`bio`는 세션 수립 후 정상(166KB HWP, 299KB PDF) — 프록시가 이미 처리 중.

- **파생 수정**: `ValidationReport.issue_counts`가 `Counter`라 `dataclasses.asdict`가 (key, value) 튜플을 Counter 생성자에 먹여 **`--json`이 이슈 발견 시 항상 TypeError로 죽던** 잠복 버그 — 평범한 dict로 교체 (attachment·markdown 리포트 둘 다).

### 13. 신규·재활성 소스의 첫 크롤은 푸시 폭탄이 된다 — 억제 절차

§11이 "재활성 후 백필분은 푸시 억제 절차(§8 참조) 필요"라고 가리키는데 **§8에는 그런 절차가 없었다.** 실제로 쓰이던 관행을 여기 적어 그 dangling reference를 끝낸다.

**왜 생기나**: 서버의 dispatch 게이트는 `pushedAt: null` + `aiSummaryAt`이 date + `crawledAt > now - 24h`다 (`notices-dispatcher.service.ts:313-316`, `maxAgeMs = 24h`). `crawledAt`은 **크롤러가 문서를 넣은 시각**이지 공지 게시일이 아니다. 그래서 소스가 처음 살아나면 floor date까지의 백로그 전체가 같은 틱에 들어오면서 전부 "24시간 내 신규"로 보인다 → 요약이 붙는 순간 한꺼번에 푸시된다.

**억제 방법**: 대상 문서의 `pushedAt`을 **epoch(1970-01-01)** 로 찍는다. 프로덕션에 이미 2,938건이 이 값을 들고 있다 — dispatcher docstring이 말하는 "Step 0 backfill"의 흔적이고, 이게 사실상의 관행이었다. `now()`가 아니라 epoch인 이유: 데이터만 보고 **"억제됨"과 "실제로 발송됨"이 구분돼야** 하기 때문 (실제 발송분 3,956건은 진짜 날짜를 갖는다).

```python
# pushedAt이 null/부재인 문서만 — 이미 발송된 것을 되돌리지 않고, 재실행은 no-op
col.update_many(
    {"sourceId": <id>, "pushedAt": {"$in": [None]}},
    {"$set": {"pushedAt": datetime(1970, 1, 1, tzinfo=timezone.utc), "pushAttempts": 0}},
)
```

**타이밍이 전부다.** 크롤(`*/30`)과 요약(`20 * * * *`) 사이에 넣어야 한다. 요약이 `aiSummaryAt`을 찍는 순간 게이트가 열린다. 크롤 직후 실행이 안전하다.

**적용 사례**: chem (2026-08-04). §12로 크롤이 처음 살아나면서 2026-03-09(service floor) 이후 백로그가 한 틱에 들어왔다 — 억제 후 신규 공지만 정상 푸시. cheme·nano 재활성 시에도 같은 절차가 필요하다.

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
