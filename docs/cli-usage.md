# CLI Usage

서브커맨드는 **8개**가 전부다. `--help`는 아무것도 import하지 않는다 (지연 click group) — 그래서 extra가 없는 코어 전용 설치에서도 도움말은 뜬다.

extra가 빠진 커맨드를 실행하면 설치 방법을 알려주고 종료한다. 어떤 커맨드가 어떤 extra를 요구하는지는 [architecture.md](architecture.md) §Execution Modes 참조.

## Commands

```bash
cd py

# ── notices: 크롤 ──────────────────────────────────────────
# 1회 incremental 크롤링 (새 글만)
python -m skkuverse_crawler notices --once

# 1회 전체 크롤링 (incremental 무시)
python -m skkuverse_crawler notices --once --all

# 특정 학과만, 지정 페이지 수
python -m skkuverse_crawler notices --once --source skku-main --pages 3

# 요청 간 딜레이 변경 (기본 500ms)
python -m skkuverse_crawler notices --once --delay 1000

# 저장소 없이 stdout JSON Lines — DB·env·웹훅 불필요 (코어 전용 설치의 인수 조건)
python -m skkuverse_crawler notices --source skku-main --json

# ── 나머지 커맨드 ──────────────────────────────────────────
# Tier-2 변경 감지 (최근 14일, 기본값)
python -m skkuverse_crawler update-check
python -m skkuverse_crawler update-check --days 7 --source skku-main

# AI 요약 (기본 batch-size: 50)
python -m skkuverse_crawler summarize
python -m skkuverse_crawler summarize --batch-size 500 --delay 2.0

# 크롤 헬스 일일 요약 1회 발송 (DISCORD_WEBHOOK_URL 필요, 미설정 시 스킵)
python -m skkuverse_crawler health-summary

# 첨부파일 메타데이터 검증
python -m skkuverse_crawler validate-attachments
python -m skkuverse_crawler validate-attachments --source cheme --no-http --json

# cleanMarkdown 렌더링 품질 검증
python -m skkuverse_crawler validate-markdown
python -m skkuverse_crawler validate-markdown --source skku-main --severity error

# tier-2가 지운 이미지 차원 복구 (기본 dry-run, 멱등)
python -m skkuverse_crawler repair-dimensions
python -m skkuverse_crawler repair-dimensions --apply

# 깨진 첨부 링크 복구 (기본 dry-run, 멱등)
python -m skkuverse_crawler repair-attachments
python -m skkuverse_crawler repair-attachments --source cal-undergrad --apply
python -m skkuverse_crawler repair-attachments --source cal-grad --refetch --apply

# 스케줄러
python -m skkuverse_crawler start
python -m skkuverse_crawler start --module notices     # 단일 모듈만
```

### `notices --json`이 암묵적으로 하는 두 가지

저장소를 안 쓰는 경로라서 두 기본값이 달라진다 — 플래그 이름이 출력 형식만 바꾸는 것처럼 보이므로 알아둘 것:

- **항상 FullSweep.** 저장소가 없으면 seen 인덱스도 없고, 그러면 정의상 모든 항목이 새 글이다. `--all`을 붙이든 안 붙이든 같다.
- **`--pages` 기본값이 1.** 캐주얼 사용자가 무심코 50페이지를 긁지 않도록 하는 가드(`STORE_LESS_DEFAULT_PAGES`). 라이브러리 facade `iter_notices()`와 **같은 상수**를 공유한다 — 두 진입점이 서로 다른 "1"을 갖지 않게.

## Options

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| **notices** | | |
| `--once` | false | 1회 실행 후 종료 (없으면 cron 모드) |
| `--all` | false | incremental 무시, 전체 크롤 (FullSweep) |
| `--source <id>` | 전체 | 특정 학과만 (sources.json의 id, 복수 지정 가능) |
| `--pages <n>` | 무제한 | 최대 페이지 수 제한 (`--json`일 땐 1) |
| `--delay <ms>` | 500 | 요청 간 최소 딜레이 (밀리초) |
| `--json` | false | stdout JSON Lines로 출력하고 **아무것도 저장하지 않음**. 로그는 stderr |
| **update-check** | | |
| `--days <n>` | 14 | 변경 감지 윈도우 (일) |
| `--source <id>` | 전체 | 특정 학과만 체크 |
| **summarize** | | |
| `--batch-size <n>` | 50 | 배치당 공지 수 |
| `--delay <sec>` | 1.0 | API 호출 간 딜레이 (초) |
| **validate-attachments** | | |
| `--source <id>` | 전체 | 특정 학과만 |
| `--limit <n>` | 무제한 | 최대 공지 수 |
| `--no-http` | false | HTTP 도달성 검사 스킵 |
| `--json` | false | JSON 형식 출력 |
| `--concurrency <n>` | 20 | HTTP 동시 요청 수 |
| **validate-markdown** | | |
| `--source <id>` | 전체 | 특정 학과만 |
| `--limit <n>` | 무제한 | 최대 공지 수 |
| `--severity` | `all` | `all`, `error`, `warning` 필터 |
| `--json` | false | JSON 형식 출력 |
| **repair-dimensions** | | |
| `--apply` | false | 실제 쓰기 (없으면 리포트만). 멱등 — 재실행 시 `repaired: 0` |
| `--source <id>` | 전체 | 특정 학과만 |
| `--limit <n>` | 무제한 | 최대 공지 수 |
| `--json` | false | JSON 형식 출력 |
| **repair-attachments** | | |
| `--apply` | false | 실제 쓰기 (없으면 리포트만). 멱등 — 재실행 시 `repaired: 0` |
| `--source <id>` | 수리 대상 전체 | 특정 학과만. 수리 모드가 없는 전략을 지정하면 경고 후 스킵 |
| `--limit <n>` | 무제한 | 최대 공지 수 |
| `--refetch` | false | 저장 데이터 대신 상세 페이지를 다시 읽는다. **원본이 삭제한 첨부를 떨어내야 할 때만** — 공지당 요청 1회 |
| `--json` | false | JSON 형식 출력 |
| **start** | | |
| `--module <name>`, `-m` | 전체 | 단일 모듈만 스케줄링 |

`health-summary`는 옵션이 없다.

## 없어진 커맨드

`backfill-content` · `backfill-attachments` · `backfill-attachment-referer` · `backfill-wpdm-attachments` 네 개는 adr-006 리팩터에서 **소멸했다**. 대체 경로:

- **null content 재크롤** → 커맨드가 아니라 크롤 경로에 흡수됐다. `WorkSeed` 포트가 매 크롤 시작 시 대상을 뽑고 `ContentRefreshed` 이벤트로 흐른다. mode 무관, 항상 돈다
- **첨부 백필 3종** → 일회성 마이그레이션이었으므로 유지할 이유가 없었다. 2026-08-04에 같은 필요가 다시 생겨 `repair-attachments`로 돌아왔다 — 아래 패턴을 따라서

일회성 복구가 또 필요하면 `repair-dimensions`가 그 패턴이다: 기본 dry-run, `--apply`로 쓰기, 멱등, **모집단이 0이 되면 삭제** (`plugins/mongo/repair.py` docstring이 이 계약을 명시한다). `repair-attachments`(`plugins/mongo/repair_attachments.py`)가 그 패턴의 두 번째 사례다.

## 소요시간 추정 (500ms 딜레이 기준)

| 시나리오 | 요청 수 | 소요시간 |
|----------|---------|----------|
| 평상시 incremental (새 글 0~5건) | 1~6 | ~3초 |
| `--pages 3` (30건 목록+상세) | 33 | ~17초 |
| 초기 풀 크롤링 50페이지 (500건) | 550 | ~5분 |
