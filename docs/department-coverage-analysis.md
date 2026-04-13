# 크롤링 학과/기관 전수 분류 + 커버리지 분석

> 작성일: 2026-04-13 | departments.json 기준 130개 엔트리

---

## 앱 카테고리 ↔ 크롤러 소스 매핑

| # | 앱 카테고리 | UI 타입 | 소스 ID | 비고 |
|---|------------|---------|---------|------|
| 1 | **학과** | 멀티셀렉트 (최대 3), 바텀시트 | dept 116개 엔트리 | 단과대 공지 + 개별 학과 |
| 2 | **학사** | 단일 소스, 필터 없음 | `skku-notice02` | 성균관대 통합(학사) |
| 3 | **장학** | 단일 소스, 필터 없음 | `skku-notice06` | 성균관대 통합(장학) |
| 4 | **취업** | 단일 소스, 필터 없음 | `skku-notice04` | 성균관대 통합(취업) |
| 5 | **채용·모집** | 단일 소스, 필터 없음 | `skku-notice05` | 성균관대 통합(채용·모집) |
| 6 | **행사** | 단일 소스, 필터 없음 | `skku-notice07` | 성균관대 통합(행사·세미나) |
| 7 | **도서관** | 캠퍼스 멀티셀렉트 (인사캠/자과캠), 바텀시트 | `lib-seoul`, `lib-suwon` | ⏳ Pyxis API 전략 추가 필요 |
| 8 | **기숙사** | 캠퍼스 멀티셀렉트 (인사캠/자과캠), 바텀시트 | `dorm-seoul`, `dorm-suwon` | jsp-dorm 전략 |

### 도서관 — Pyxis API (추가 예정)

`lib.skku.edu`는 Angular SPA + Pyxis 플랫폼. 기존 HTML 스크래핑 전략과 다른 JSON API 방식:

- **목록**: `GET lib.skku.edu/pyxis-api/1/bulletin-boards/1/bulletins?max=10&offset=0`
- **캠퍼스 필터**: `bulletinCategoryId=2` (인사캠/중앙학술정보관), `=3` (자과캠/삼성학술정보관), `=24` (전체)
- **상세**: `GET lib.skku.edu/pyxis-api/1/bulletins/{id}` → `content` (HTML)
- **총 공지**: ~1,515건 (중앙 351 + 삼성 348 + 전체 428 + 미분류 388)

### 미결정 사항

- 센터 10개 (건강센터, 인권센터 등): 학과 목록에 포함 여부 미정
- `hakbu-portal-*` 시리즈 (8개): `skku-notice*`와 역할 중복 가능, 추후 결정
- `skku-main` (notice01) vs `skku-notice02`: 학사 소스로 `skku-notice02` 채택
- `skku-notice08` (일반): 앱 카테고리에 미포함, 추후 결정

---

## 전략별 분포

| 전략 | 수 | 대상 |
|------|----|------|
| `skku-standard` | 122 | 표준 성대 게시판 (`skb.skku.edu`, `{dept}.skku.edu`) |
| `wordpress-api` | 1 | 화학공학과 (`cheme.skku.edu`) |
| `skkumed-asp` | 1 | 의과대학 (`www.skkumed.ac.kr`, euc-kr) |
| `jsp-dorm` | 2 | 기숙사 (`dorm.skku.edu`) |
| `custom-php` | 2 | 건설환경공학부 (`cal.skku.edu`) |
| `gnuboard` | 3 | 생명과학과, 약학대학 (`bio`/`pharm.skku.edu`) |
| `gnuboard-custom` | 1 | 나노공학과 (`nano.skku.edu`) |

---

## 1. 단과대학별 학과 분류

### 인문사회과학캠퍼스 (서울)

#### 학부대학

| ID | 이름 |
|----|------|
| `hakbu` | 학부대학(계열제) |

#### 유학대학

| ID | 이름 |
|----|------|
| `scos-undergrad` | 유학대학(유학동양학과)(학부생) |
| `scos-grad` | 유학대학(유학동양학과)(대학원) |

#### 문과대학

| ID | 이름 | 비고 |
|----|------|------|
| `liberalarts-undergrad` | 문과대학(학부생) | 단과대 공지 |
| `liberalarts-grad` | 문과대학(대학원) | 단과대 공지 |
| `korean-undergrad` | 국어국문학과(학부생) | |
| `korean-grad` | 국어국문학과(대학원) | |
| `english-undergrad` | 영어영문학과(학부생) | |
| `english-grad` | 영어영문학과(대학원) | |
| `french-undergrad` | 프랑스어문학과(학부생) | |
| `french-grad` | 프랑스어문학과(대학원) | |
| `chinese-undergrad` | 중어중문학과(학부생) | |
| `chinese-grad` | 중어중문학과(대학원) | |
| `german` | 독어독문학과 | 학부만 |
| `russian` | 러시아어문학과 | 학부만 |
| `klcc-undergrad` | 한문학과(학부생) | |
| `klcc-grad` | 한문학과(대학원) | |
| `history-undergrad` | 사학과(학부생) | |
| `history-grad` | 사학과(대학원) | |
| `philosophy-undergrad` | 철학과(학부생) | |
| `philosophy-grad` | 철학과(대학원) | |
| `lis-undergrad` | 문헌정보학과(학부생) | |
| `lis-grad` | 문헌정보학과(대학원) | |

#### 사회과학대학

| ID | 이름 | 비고 |
|----|------|------|
| `sscience-undergrad` | 사회과학대학(학부생) | 단과대 공지 |
| `sscience-grad` | 사회과학대학(대학원) | 단과대 공지 |
| `psd-undergrad` | 정치외교학과(학부생) | |
| `psd-grad` | 정치외교학과(대학원) | |
| `mediacomm-undergrad` | 미디어커뮤니케이션학과(학부생) | |
| `mediacomm-grad` | 미디어커뮤니케이션학과(대학원) | |
| `soc` | 사회학과 | 학부만 |
| `welfare` | 사회복지학과 | 학부만 |
| `psych-undergrad` | 심리학과(학부생) | |
| `psych-grad` | 심리학과(대학원) | |
| `cf` | 소비자학과 | 학부만 |
| `child-undergrad` | 아동·청소년학과(학부생) | |
| `child-grad` | 아동·청소년학과(대학원) | |
| `gld` | 글로벌리더학부 | 학부만 |

#### 경제대학

| ID | 이름 | 비고 |
|----|------|------|
| `ecostat-undergrad` | 경제대학(학부생) | 단과대 공지 |
| `ecostat-grad` | 경제대학(대학원) | 단과대 공지 |
| `globalecon` | 글로벌경제학과 | |
| `stat-undergrad` | 통계학과(학부생) | |
| `stat-grad` | 통계학과(대학원) | |

#### 경영대학

| ID | 이름 | 비고 |
|----|------|------|
| `biz-undergrad` | 경영대학(학부생) | 단과대 공지 |
| `biz-grad` | 경영대학(대학원) | 단과대 공지 |
| `globalbiz` | 글로벌경영학과 | |

#### 사범대학

| ID | 이름 | 비고 |
|----|------|------|
| `coe-undergrad` | 사범대학(학부생) | 단과대 공지 |
| `coe-grad` | 사범대학(대학원) | 단과대 공지 |
| `skku-edu-undergrad` | 교육학과(학부생) | |
| `skku-edu-grad` | 교육학과(대학원) | |
| `klccedu` | 한문교육과 | |
| `mathedu` | 수학교육과 | |
| `comedu-undergrad` | 컴퓨터교육과(학부생) | |
| `comedu-grad` | 컴퓨터교육과(대학원) | |

#### 예술대학

| ID | 이름 | 비고 |
|----|------|------|
| `art-undergrad` | 예술대학(학부생) | 단과대 공지 |
| `art-grad` | 예술대학(대학원) | 단과대 공지 |
| `design-undergrad` | 디자인학과(학부생) | |
| `design-grad` | 디자인학과(대학원) | |
| `dance` | 무용학과 | |
| `acting` | 연기예술학과 | |
| `fashion-undergrad` | 의상학과(학부생) | |
| `fashion-grad` | 의상학과(대학원) | |

#### 법학전문대학원

| ID | 이름 |
|----|------|
| `sls-general` | 법학과(일반대학원) |
| `sls-special` | 법학전문대학원 |

---

### 자연과학캠퍼스 (수원)

#### 자연과학대학

| ID | 이름 | 전략 |
|----|------|------|
| `cscience-undergrad` | 자연과학대학(학부생) | skku-standard (단과대 공지) |
| `cscience-grad` | 자연과학대학(대학원) | skku-standard (단과대 공지) |
| `bio-undergrad` | 생명과학과(학부) | gnuboard |
| `bio-grad` | 생명과학과(대학원) | gnuboard |
| `math-undergrad` | 수학과(학부생) | skku-standard |
| `math-grad` | 수학과(대학원) | skku-standard |
| `physics` | 물리학과 | skku-standard |
| `chem` | 화학과 | skku-standard |

#### 정보통신대학

| ID | 이름 |
|----|------|
| `ice-undergrad` | 정보통신대학(학부생) — 단과대 공지 |
| `ice-grad` | 정보통신대학(대학원) — 단과대 공지 |
| `eee-undergrad` | 전자전기공학부(학부생) |
| `eee-job` | 전자전기공학부(취업) |
| `mcce` | 소재부품융합공학과 |

#### 소프트웨어융합대학

| ID | 이름 |
|----|------|
| `sw-undergrad` | 소프트웨어융합대학(학부생) — 단과대 공지 |
| `sw-grad` | 소프트웨어융합대학(대학원) — 단과대 공지 |
| `cse-undergrad` | 소프트웨어학과(학부생) |
| `cse-grad` | 소프트웨어학과(대학원) |
| `sco` | 글로벌융합학부 |
| `intelligentsw` | 지능형소프트웨어학과 |

#### 공과대학

| ID | 이름 | 전략 |
|----|------|------|
| `enc-undergrad` | 공과대학(학부생) | skku-standard (단과대 공지) |
| `enc-grad` | 공과대학(대학원) | skku-standard (단과대 공지) |
| `cheme` | 화학공학과 | wordpress-api |
| `amse-undergrad` | 신소재공학부(학부생) | skku-standard |
| `amse-grad` | 신소재공학부(대학원) | skku-standard |
| `mech-undergrad` | 기계공학부(학부생) | skku-standard |
| `mech-grad` | 기계공학부(대학원) | skku-standard |
| `cal-undergrad` | 건설환경공학부(학부) | custom-php |
| `cal-grad` | 건설환경공학부(대학원) | custom-php |
| `ie-undergrad` | 시스템경영공학과(학부생) | skku-standard |
| `ie-grad` | 시스템경영공학과(대학원) | skku-standard |
| `arch` | 건축학과 | skku-standard |
| `nano` | 나노공학과 | gnuboard-custom |
| `qie` | 양자정보공학과 | skku-standard |

#### 약학대학

| ID | 이름 | 전략 |
|----|------|------|
| `pharm` | 약학대학 | gnuboard |

#### 생명공학대학

| ID | 이름 |
|----|------|
| `biotech-undergrad` | 생명공학대학(학부생) — 단과대 공지 |
| `biotech-grad` | 생명공학대학(대학원) — 단과대 공지 |
| `foodlife-undergrad` | 식품생명공학과(학부생) |
| `foodlife-grad` | 식품생명공학과(대학원) |
| `biomecha` | 바이오메카트로닉스학과 |
| `gene` | 융합생명공학과 |

#### 스포츠과학대학

| ID | 이름 |
|----|------|
| `sport-undergrad` | 스포츠과학대학(학부생) |
| `sport-grad` | 스포츠과학대학(대학원) |

#### 의과대학

| ID | 이름 | 전략 |
|----|------|------|
| `medicine` | 의과대학 | skkumed-asp (euc-kr) |

#### 성균융합원

| ID | 이름 |
|----|------|
| `ics` | 성균융합원 — 원 공지 |
| `gbme-undergrad` | 글로벌바이오메디컬공학과(학부생) |
| `gbme-grad` | 글로벌바이오메디컬공학과(대학원) |
| `aicon` | 응용AI융합학부 |
| `energy` | 에너지학과 |

---

## 2. 대학 본부 통합공지 (16개)

| ID | 이름 |
|----|------|
| `skku-main` | 학부통합(학사) |
| `skku-notice02` | 성균관대_통합(학사) |
| `skku-notice03` | 성균관대_통합(입학) |
| `skku-notice04` | 성균관대_통합(취업) |
| `skku-notice05` | 성균관대_통합(채용·모집) |
| `skku-notice06` | 성균관대_통합(장학) |
| `skku-notice07` | 성균관대_통합(행사·세미나) |
| `skku-notice08` | 성균관대_통합(일반) |
| `hakbu-portal` | 학부통합(전체) |
| `hakbu-portal-sugang` | 학부통합(수강신청) |
| `hakbu-portal-admission` | 학부통합(입학) |
| `hakbu-portal-job` | 학부통합(취업) |
| `hakbu-portal-recruit` | 학부통합(채용·모집) |
| `hakbu-portal-scholarship` | 학부통합(장학) |
| `hakbu-portal-event` | 학부통합(행사·세미나) |
| `hakbu-portal-general` | 학부통합(일반) |

## 3. 부속기관 / 센터 (11개)

| ID | 이름 |
|----|------|
| `health` | 건강센터 |
| `ccrf` | 공동기기원 |
| `saint` | 나노과학기술원 |
| `chec` | 성균인성교육센터 |
| `helper` | 인권센터 |
| `support` | 장애학생지원센터 |
| `scc` | 카운슬링센터 |
| `success` | 학생성공센터 |
| `larc` | 실험동물센터 |
| `dorm-seoul` | 명륜학사 (인사캠 기숙사) |
| `dorm-suwon` | 봉룡학사 (자과캠 기숙사) |

## 4. 융합전공 / 연계전공 (4개)

| ID | 이름 |
|----|------|
| `sco-data` | 데이터사이언스융합전공 |
| `sco-ai` | 인공지능융합전공 |
| `sco-magnetic` | 자기설계융합전공 |
| `ase` | 차세대반도체공학연계전공 |

## 5. 대학원 — 전문/특수 (4개)

| ID | 이름 |
|----|------|
| `sls-general` | 법학과(일반대학원) |
| `sls-special` | 법학전문대학원 |
| `gsg` | 행정학과(국정전문대학원) |
| `quant` | 퀀트응용경제학과 |

---

## 6. 누락 분석 (SKKU 공식 조직도 대비)

### 학부/대학원 미분리 (단일 엔트리만 존재하는 학과)

게시판이 1개뿐이거나 대학원 게시판이 없는 경우일 수 있음. 확인 필요:

| ID | 이름 |
|----|------|
| `german` | 독어독문학과 |
| `russian` | 러시아어문학과 |
| `soc` | 사회학과 |
| `welfare` | 사회복지학과 |
| `cf` | 소비자학과 |
| `gld` | 글로벌리더학부 |
| `globalecon` | 글로벌경제학과 |
| `globalbiz` | 글로벌경영학과 |
| `klccedu` | 한문교육과 |
| `mathedu` | 수학교육과 |
| `dance` | 무용학과 |
| `acting` | 연기예술학과 |
| `physics` | 물리학과 |
| `chem` | 화학과 |
| `mcce` | 소재부품융합공학과 |
| `intelligentsw` | 지능형소프트웨어학과 |
| `arch` | 건축학과 |
| `qie` | 양자정보공학과 |
| `nano` | 나노공학과 |
| `biomecha` | 바이오메카트로닉스학과 |
| `gene` | 융합생명공학과 |
| `energy` | 에너지학과 |
| `aicon` | 응용AI융합학부 |
| `cheme` | 화학공학과 |

### 완전 누락 — 학과

| 학과 | 소속 | 비고 |
|------|------|------|
| 경제학과 | 경제대학 | 단과대 공지(`ecostat`)에 포함? 개별 게시판 확인 필요 |
| 행정학과 | 사회과학대학 | `gsg`는 국정전문대학원만. 학부 행정학과 누락 |
| 반도체시스템공학과 | 정보통신대학 | 신설 학과 |
| 반도체융합공학과 | 정보통신대학 | 신설 학과 |
| 미술학과 | 예술대학 | `art` 단과대 공지에 포함? |
| 영상학과 | 예술대학 | `art` 단과대 공지에 포함? |
| 바이오신약·규제과학과 | 약학대학 | 신설 |
| 배터리학과 | 성균융합원 | 신설 |

### 완전 누락 — 특수대학원

| 대학원 |
|--------|
| 유학대학원 |
| 교육대학원 |
| 정보통신대학원 |
| 언어·AI대학원 |
| 사회복지대학원 |
| 임상간호대학원 |
| 경영대학원 |
| 미디어문화융합대학원 |
| 글로벌창업대학원 |
| 첨단국방대학원 |

### 완전 누락 — 부속기관

| 기관 | URL | 비고 |
|------|-----|------|
| 도서관 | `lib.skku.edu` | 공지 있음 |
| 성균어학원 | `sli.skku.edu` | 어학 프로그램 공지 |
| 교육개발센터 (CTL) | `ctl.skku.edu` | 교수법/수업 관련 |
| 창업지원단 | `startup.skku.edu` | 창업 관련 |
| 국제교류원 | — | 교환학생 공지 |

### 행정기관 (별도 크롤링 필요성 낮음)

행정기관(교무처, 학생처, 입학처, 국제처 등)의 공지는 대부분 `skku.edu` 통합공지(`notice01`~`notice08`)에 올라가므로 별도 크롤링 불필요할 가능성 높음.

---

## 요약 통계

| 분류 | 크롤링 중 | 누락 추정 |
|------|----------|----------|
| 단과대학 공지 (학부+대학원) | 16개 대학 | — |
| 개별 학과 (학부) | ~55개 | ~8개 |
| 개별 학과 (대학원) | ~30개 | 위 학부만 있는 ~24개 중 확인 필요 |
| 대학 본부 통합공지 | 16개 | — (충분) |
| 부속기관/센터 | 11개 | ~5개 |
| 융합/연계전공 | 4개 | 확인 필요 |
| 전문/특수대학원 | 2개 | ~10개 |
| 행정기관 | 0개 (통합공지로 커버) | 별도 필요성 낮음 |
