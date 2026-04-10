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
