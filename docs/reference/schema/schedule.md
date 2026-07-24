---
title: schedule 컬렉션 스키마
type: reference
status: accepted
owner: zoyoong124@gmail.com
last-updated: 2026-07-24
audience: internal
---

# schedule 컬렉션 스키마

> `skku_notices.schedule` 컬렉션 — SKKU 학사일정(academic calendar). `notices`와 달리 **학년도(academic year) 단위로 문서 1개**를 두고, 그 안에 이벤트 배열을 담는다. SSOT 코드는 `schedule/` 모듈.

## 문서 모델 — 학년도 단위 자연키

`COLLECTION_NAME = "schedule"` (`schedule/module.py`). 한 학년도 = 한 문서, `_id`가 학년도(natural key)라 정정 시 `events` 배열 전체를 한 번의 `$set`으로 교체한다 (stale 중복 없음). 연-도큐먼트 형태 (`schedule/module.py::_crawl_year`):

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `_id` | `int` | 학년도 (자연키). 예: `2026` |
| `academicYear` | `int` | `_id`와 동일 (조회 편의) |
| `events` | `ScheduleEvent[]` | 이벤트 배열 (아래) |
| `eventCount` | `int` | `len(events)` |
| `yearHash` | `str` | 이벤트 집합 해시 — write 게이트 (아래) |
| `sourceUrl` | `str` | 해당 학년도 원본 URL |
| `updatedAt` | `datetime` | 마지막 변경 시각 (repository가 `$set`) |
| `crawledAt` | `datetime` | 최초 삽입 시각 (`$setOnInsert`) |

### ScheduleEvent (배열 원소)

`schedule/models.py`의 `ScheduleEvent` dataclass:

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `month` | `int` | 원본이 이벤트를 분류한 학년도 월 그룹 (3–12, +1–2는 다음 해로 넘어감). **`startDate`의 달력 월과 반드시 같지는 않다** (학년도 경계) |
| `startDate` | `str` | `YYYY-MM-DD` |
| `endDate` | `str \| None` | `YYYY-MM-DD` 또는 `None` (단일일 이벤트 / 종료일 없음) |
| `content` | `str` | 일정 내용 |

## Upsert — hash 게이트

`schedule/repository.py::upsert_year`는 `yearHash`로 write를 게이트한다: 저장된 `yearHash`가 새 것과 같으면 **DB write 자체를 건너뛴다**(`"skipped"`). 다르면 `_id` 제외 전 필드를 `$set`, 최초면 `$setOnInsert`로 `crawledAt` 세팅. 반환값은 `"skipped" | "inserted" | "updated"`.

이 컬렉션은 전용 인덱스를 만들지 않는다 (`_id` 자연키만으로 조회).

## 크롤 주기

`schedule` 모듈의 `ModuleConfig` cron은 `30 5 * * *` (하루 1회), `run_on_start=True`. CLI는 `schedule` 명령 (`--year`, `--once`) — [reference/cli.md](../cli.md).

## 관련 문서

- [notices.md](notices.md) — 공지 컬렉션 스키마
- [explanation/module-system.md](../../explanation/module-system.md) — schedule가 따르는 모듈 프레임워크
- [umbrella data-topology](https://github.com/spencer0124/skkuverse/blob/main/docs/architecture/data-topology.md)
