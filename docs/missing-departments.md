# 누락/보류 학과 추적 문서

> ⚠️ **이 파일은 자동 생성 대상이 아닙니다.** `generate_artifacts.py`의 codegen은 이 파일을 건드리지 않으니 안전하게 손으로 갱신하세요.
>
> ⚠️ `docs/department-coverage-analysis.md`, `docs/departments-by-college.md`, `docs/departments-by-app-category.md` 세 파일은 **codegen이 매번 덮어씁니다**. 그 파일들에 누락 분석을 적으면 다음 codegen에서 사라집니다.

## 목적

SKKU 공식 조직도엔 있지만 `sources.json`에 들어 있지 않은 학과/기관을 *왜 빠졌는지* 사유와 함께 추적합니다. 항목별 검증이 끝나면 둘 중 하나로 처리:

1. **사이트가 있고 크롤 가능** → `sources.json`에 신규 entry 추가, `crawlAvailable: true`로 활성화
2. **사이트가 없거나 로그인 필요 등 구조적 미지원** → `sources.json`에 entry 추가하되 `crawlAvailable: false` + `excludeReason` 채움 → 앱이 회색 처리 + 사유 안내

## 출처 (Origin)

이 문서의 원본은 **PR #11 (`30e28f0`, 2026-04-13)** 의 `docs/department-coverage-analysis.md` § 6 "누락 분석". 해당 narrative 섹션이 SSOT codegen 마이그레이션(`5ea5b6a`/`f60a109`/`ffa01f8`) 과정에서 자동 생성형 표로 대체되며 사라졌고, 이 문서로 부활시킴.

원본 보기: `git show 30e28f0:docs/department-coverage-analysis.md`

## 검증 상태 범례

| 마커 | 의미 |
|:--:|---|
| ⏳ | 미검증 — 사이트 존재 여부, 크롤 가능 여부 미확인 |
| ✅ | 검증 완료 — 사이트 존재 + 크롤 가능 → `sources.json` 추가 예정 |
| 🔒 | 검증 완료 — 로그인 필요 → `excludeReason: loginRequired` |
| 🌐 | 검증 완료 — 사이트 없음 → `excludeReason: noWebsite` |
| 🔌 | 검증 완료 — 외부/자체 시스템 → `excludeReason: externalSystem` |
| 🏫 | 검증 완료 — 학내망 한정 → `excludeReason: accessRestricted` |
| ⏸ | 검증 완료 — 일시 점검/폐쇄 → `excludeReason: temporarilyUnavailable` |
| 🚫 | 정책상 제외 — 학과 카테고리에 부적합 (행정기관 등). 별도 결정 |

---

## 1. 완전 누락 — 학과 (8건)

| 상태 | 학과 | 소속 | PR #11 비고 | excludeReason 후보 | 메모 |
|:--:|---|---|---|---|---|
| ⏳ | 경제학과 | 경제대학 | 단과대 공지(`ecostat`)에 포함? 개별 게시판 확인 필요 | — | — |
| ⏳ | 행정학과 (학부) | 사회과학대학 | `gsg`는 국정전문대학원만. 학부 행정학과 누락 | — | — |
| ⏳ | 반도체시스템공학과 | 정보통신대학 | 신설 학과 | — | — |
| ⏳ | 반도체융합공학과 | 정보통신대학 | 신설 학과 | — | — |
| ⏳ | 미술학과 | 예술대학 | `art` 단과대 공지에 포함? | — | — |
| ⏳ | 영상학과 | 예술대학 | `art` 단과대 공지에 포함? | — | — |
| ⏳ | 바이오신약·규제과학과 | 약학대학 | 신설 | — | — |
| ⏳ | 배터리학과 | 성균융합원 | 신설 | — | — |

## 2. 완전 누락 — 특수대학원 (10건)

| 상태 | 대학원 | excludeReason 후보 | 메모 |
|:--:|---|---|---|
| ⏳ | 유학대학원 | — | — |
| ⏳ | 교육대학원 | — | — |
| ⏳ | 정보통신대학원 | — | — |
| ⏳ | 언어·AI대학원 | — | — |
| ⏳ | 사회복지대학원 | — | — |
| ⏳ | 임상간호대학원 | — | — |
| ⏳ | 경영대학원 | — | — |
| ⏳ | 미디어문화융합대학원 | — | — |
| ⏳ | 글로벌창업대학원 | — | — |
| ⏳ | 첨단국방대학원 | — | — |
| ✅ | 중국대학원 | — | `gsc.skku.edu/gsc/notice.do` (skku-standard) → sources.json#gsc |

## 3. 완전 누락 — 부속기관 (5건 중 1건은 이후 추가됨)

| 상태 | 기관 | URL | excludeReason 후보 | 메모 |
|:--:|---|---|---|---|
| ✅ | 도서관 | `lib.skku.edu` | — | **이후 추가됨** — `lib-all`/`lib-hssc`/`lib-nsc` (Pyxis API 전략) |
| ⏳ | 성균어학원 | `sli.skku.edu` | — | 어학 프로그램 공지 |
| ⏳ | 교육개발센터 (CTL) | `ctl.skku.edu` | — | 교수법/수업 관련 |
| ⏳ | 창업지원단 | `startup.skku.edu` | — | 창업 관련 |
| ⏳ | 국제교류원 | (URL 미확인) | — | 교환학생 공지 |

## 4. PR #11 미결정 사항 (정책 결정 필요)

학과/누락이 아니라 *카테고리/UI 정책* 차원의 미결정 항목들. PR #11 § "미결정 사항"에서 그대로:

| 상태 | 항목 | 메모 |
|:--:|---|---|
| ⏳ | 센터 10개 (건강센터, 인권센터 등) | 학과 목록 포함 여부 미정 |
| ✅ | `hakbu-portal-*` 시리즈 8개 | **제외 확정** (2026-07-30) — 콘텐츠 실측 결과 `skku-notice*` 포털 공지의 신디케이션 미러로 확인, sources.json에서 삭제. 근거·재검토 조건은 [adr-005](decisions/adr-005-hakbu-board-remap.md) |
| ⏳ | `skku-main` (notice01) vs `skku-notice02` | 학사 소스로 `skku-notice02` 채택됨 (확정) |
| ⏳ | `skku-notice08` (일반) | 앱 카테고리에 미포함, 추후 결정 |

## 5. 학부/대학원 미분리 (24건 — 보류 의미는 아님)

> 이 절은 *누락이 아닙니다*. 한쪽 게시판만 운영 중인 학과들로, 양쪽 게시판이 *실제로 운영되지 않으면* sources.json에 추가할 게 없는 정상 상태. 검증 시 양쪽이 운영되는 케이스만 추가.

| ID (현재 entry) | 이름 |
|---|---|
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

---

## 검증 워크플로

각 항목 검증할 때:

1. 해당 학과/기관 공식 사이트 직접 방문 (또는 Google 검색)
2. *공지사항 게시판이 있는가?* 여부 확인
3. 게시판 접근 시 *로그인 필요한가?* 확인
4. 표 안의 **상태 마커** 갱신 (`⏳` → 적절한 다른 마커)
5. **excludeReason 후보** 컬럼에 enum 키 적기 (`loginRequired` / `noWebsite` / `externalSystem` / `accessRestricted` / `temporarilyUnavailable`)
6. **메모** 컬럼에 사이트 URL이나 특이사항 기록

검증이 끝난 항목은 다음 두 갈래:

- **사이트 있음 + 크롤 가능** → `sources.json`에 신규 entry 추가 PR. 이 표에서는 `✅`로 두고 메모에 "→ sources.json#{id}"로 링크.
- **구조적 미지원** → `sources.json`에 `crawlAvailable: false` + `excludeReason` 채워서 PR. 이 표에서는 사유 마커(🔒/🌐/🔌/🏫/⏸)로 갱신.

---

## 관련 파일

- `sources.json` — SSOT
- `py/scripts/generate_artifacts.py` — 검증 룰 (3종 reject 포함). `crawlAvailable: false`이면서 `excludeReason: null`인 entry는 codegen reject.
- `docs/department-coverage-analysis.md` — 자동 생성, *현재 활성*인 학과만 표시 (이 파일이 다루는 *누락* 학과는 표시하지 않음 by design).
- `~/project/skkuverse/skkuverse-app/packages/shared/src/notices/types.ts` — `ExcludeReasonKey` enum (앱 i18n 키와 1:1 매핑).
