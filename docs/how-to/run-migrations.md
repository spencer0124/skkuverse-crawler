---
title: 일회성 마이그레이션 실행하기
type: how-to
status: accepted
owner: zoyoong124@gmail.com
last-updated: 2026-07-24
audience: internal
---

# 일회성 마이그레이션 실행하기

> `py/scripts/`의 일회성 DB 마이그레이션 스크립트 실행 절차. 모두 **dry-run이 기본**이고 `--apply`로만 실제 쓰기가 일어난다.

## 개요

정규 크롤 파이프라인과 별개로, 스키마/데이터가 바뀔 때 기존 문서를 손보는 일회성 스크립트다. 공통 규약:

- **dry-run 기본** — `--apply` 없이는 변경 사항만 출력하고 쓰지 않는다.
- `--env {production|development|test}`로 대상 DB 선택 (env 라우팅은 `shared/config.py::_db_name`).
- `cd py`에서 실행.

## 스크립트

### `migrate_oversized_articleno.py`

webflow-skku 소스(예: 영상학과)는 숫자 게시글 id가 없어 slug 해시로 `articleNo`를 합성한다. 구 56-bit 해시가 `2^31`을 넘겨 BSON Long으로 저장 → 앱이 0으로 강제해 상세 링크가 전부 404 났다. 전략이 31-bit 해시(BSON Int32)로 바뀌었고, 이 스크립트가 **기존 문서의 `articleNo`를 새 해시로 재계산**한다 (content/summary는 안 건드림).

- 안전장치: `detailPath`로 slug를 복원해 저장된 `articleNo`가 **구 56-bit 해시와 일치하는지 검증**하고, 불일치·범위초과·중복이면 쓰기 없이 중단.
- `--apply` 시 명시적 `yes` 입력을 요구. `--source`로 특정 소스만.

```bash
python scripts/migrate_oversized_articleno.py --env development           # dry-run
python scripts/migrate_oversized_articleno.py --env production --apply
```

> [!WARNING]
> **배포 순서 주의**: `--apply` 전에 새 크롤러 코드를 대상 env에 먼저 배포해야 한다. 안 그러면 다음 크롤이 구 56-bit 해시를 다시 계산해 매치 실패 → 깨진 문서를 중복 삽입한다.

### `cleanup_summary_fields.py`

AI 요약 응답 스키마가 **flat `startDate/endDate/location` → `periods[]`/`locations[]` 배열**로 바뀌면서, 섞인 구형 요약 데이터를 전부 unset해 다음 요약 사이클이 새 스키마로 재요약하게 한다. (실행 후 `find_unsummarized()`가 이들을 다음 cron에 다시 집는다.)

```bash
python scripts/cleanup_summary_fields.py                          # dry-run, 현재 env
python scripts/cleanup_summary_fields.py --env production --apply
```

> 이 스키마 변경이 [reference/notices-data-contract.md](../reference/notices-data-contract.md)의 구 flat 요약 필드가 superseded인 이유다.

## 검증

- dry-run 출력의 대상 건수/샘플을 먼저 확인한다.
- `--apply` 후 영향 컬렉션을 스팟 체크 (`notices`의 `articleNo` 타입 / `summary*` 존재 여부).

## 관련 문서

- [reference/schema/notices.md](../reference/schema/notices.md) — 대상 필드
- [reference/cli.md](../reference/cli.md) — 정규 크롤/요약 명령
