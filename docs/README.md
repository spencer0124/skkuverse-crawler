---
title: Docs Index & Conventions
type: reference
status: accepted
owner: zoyoong124@gmail.com
last-updated: 2026-07-24
audience: internal
---

# Docs Index & Conventions

> skkuverse-crawler 문서의 인덱스이자 작성 규칙의 단일 진실 출처(SSOT). 새 문서를 쓰기 전에 이 파일을 읽는다. 시스템 전체(레포 경계를 넘는) 그림은 [umbrella 저장소](https://github.com/spencer0124/skkuverse)에 있다 — 이 레포 문서는 **크롤러의 몫**만 다룬다.

## 폴더 구조 (Diátaxis)

문서는 [Diátaxis](https://diataxis.fr/) 분류 + 내부 전용 폴더로 나눈다. **분류 기준은 주제가 아니라 독자의 니즈**다. (skkuverse-app / skkuverse-server와 동일한 컨벤션.)

| 폴더 | 니즈 | 내용 |
| --- | --- | --- |
| `how-to/` | 해내기 (작업) | 특정 목표를 달성하는 절차 런북 |
| `reference/` | 찾아보기 (정보) | 계약·스펙·스키마·CLI의 권위 있는 사실 |
| `explanation/` | 이해하기 (맥락) | 왜 이렇게 되어 있는지, 아키텍처·메커니즘 |
| `decisions/` | — | ADR (`NNNN-kebab-title.md`) |
| `internal/` | — | 운영 추적·포스트모템 (`YYYY-MM-topic.md`) |
| `archive/` | — | 이관·해결된 과거 스냅샷 (superseded) |

**한 문서 = 한 니즈.** 절차와 배경 설명이 섞이면 문서를 쪼개고 서로 링크한다.

## 문서 인덱스

### how-to (런북)

| 문서 | 요약 |
| --- | --- |
| [how-to/add-a-source.md](how-to/add-a-source.md) | 학과/기관 소스 추가 — `sources.json` 편집 → codegen 재생성 절차 |
| [how-to/add-a-module.md](how-to/add-a-module.md) | 새 크롤 모듈 추가 (식당 등이 따르는 길) |
| [how-to/run-migrations.md](how-to/run-migrations.md) | 일회성 DB 마이그레이션 스크립트 실행 (dry-run → apply) |

### reference (계약·스펙)

| 문서 | 요약 |
| --- | --- |
| [reference/cli.md](reference/cli.md) | 전체 CLI 명령·플래그 레퍼런스 |
| [reference/notices-data-contract.md](reference/notices-data-contract.md) | 공지 API를 만드는 소비자용 데이터 계약 (필드·전략별 가용성·샘플) |
| [reference/schema/notices.md](reference/schema/notices.md) | `notices` 컬렉션 canonical 스키마 (크롤러 필드 + AI summary\* write-back) |
| [reference/schema/schedule.md](reference/schema/schedule.md) | `schedule` 컬렉션 스키마 (학사일정) |
| [reference/strategies/](reference/strategies/) | 전략별 게시판 DOM·셀렉터 스펙 (9종) |
| [reference/coverage/](reference/coverage/) | **codegen 생성** — sources.json 커버리지/분류 (수동 편집 금지) |

### explanation (메커니즘·배경)

| 문서 | 요약 |
| --- | --- |
| [explanation/architecture.md](explanation/architecture.md) | 시스템 구조·설계 결정·디렉토리 레이아웃·데이터 흐름 |
| [explanation/crawl-flow.md](explanation/crawl-flow.md) | 크롤 라이프사이클 단계별 워크스루 |
| [explanation/module-system.md](explanation/module-system.md) | 모듈 프레임워크 (`CrawlModule` Protocol + registry) — 확장성 |
| [explanation/mcp-server.md](explanation/mcp-server.md) | 크롤러를 MCP로 공개하는 설계 의도 (public) |

### decisions (ADR)

| 문서 | 상태 |
| --- | --- |
| [decisions/0001-adopt-diataxis-docs-structure.md](decisions/0001-adopt-diataxis-docs-structure.md) | accepted |
| [decisions/0002-config-driven-strategy-pattern.md](decisions/0002-config-driven-strategy-pattern.md) | accepted |
| [decisions/0003-modular-crawl-framework.md](decisions/0003-modular-crawl-framework.md) | accepted |

### internal / archive

| 문서 | 요약 |
| --- | --- |
| [internal/missing-departments.md](internal/missing-departments.md) | 아직 `sources.json`에 없는 학과 추적 (운영) |
| [archive/known-issues-2026h1.md](archive/known-issues-2026h1.md) | 2026 상반기 해결된 이슈 로그 (스냅샷) |

## 문서 작성 규칙

### 1. Frontmatter (필수)

모든 **hand-written** 문서는 YAML frontmatter로 시작한다:

```yaml
---
title: <Title Case 제목>
type: how-to | reference | explanation | adr | postmortem
status: draft | accepted | superseded | deprecated
owner: zoyoong124@gmail.com
last-updated: YYYY-MM-DD
audience: internal | public
---
```

- `status: superseded/deprecated`일 때는 본문 첫머리에 현행 SSOT 링크를 남긴다.
- 문서 내용을 실질적으로 고칠 때마다 `last-updated`를 갱신한다.
- **예외**: `reference/coverage/`의 3개 파일은 `generate_artifacts.py`가 생성하므로 frontmatter 없이 auto-gen 배너를 유지한다. 수동 편집 금지.

### 2. 골격

frontmatter 다음은 `# H1`(문서당 하나) → `> 한 줄 요약` → `##` 섹션(레벨 건너뛰기 금지). 새 문서는 [`_template.md`](_template.md)를 복사해서 시작한다.

### 3. 값을 복사하지 말고 출처를 가리켜라

**버전·수치·개수·라인번호를 문서에 하드코딩하지 않는다.** 코드가 바뀌면 문서가 조용히 거짓말을 시작한다 (이 레포의 소스 개수가 문서마다 134/147/149로 갈렸던 것이 그 증거).

- ❌ `크롤 소스는 149개다`
- ✅ 개수/분류는 [reference/coverage/department-coverage-analysis.md](reference/coverage/department-coverage-analysis.md)(codegen SSOT)를 가리킨다
- ❌ `models.py:28-50`
- ✅ `notices/models.py`의 `Notice` dataclass — 클래스/함수 이름으로 가리킨다 (라인번호는 드리프트)

### 4. 파일명·서식

- kebab-case 소문자 `.md`. ADR은 `NNNN-kebab-title.md`, 포스트모템은 `YYYY-MM-topic.md`.
- 코드펜스 언어 태그 필수 (`python`, `bash`, `json`). 구조화된 사실은 표로. 본문 한국어, 기술 용어 영어.
- 주의/경고는 GitHub admonition (`> [!NOTE]`, `> [!WARNING]`).

## 관련

- [루트 CLAUDE.md](../CLAUDE.md) — 에이전트 온보딩 (Commands는 [reference/cli.md](reference/cli.md)를 가리킨다)
- [umbrella 저장소](https://github.com/spencer0124/skkuverse) — 시스템 전체 흐름·데이터 토폴로지
