---
title: 모듈형 크롤 프레임워크 (CrawlModule Protocol + registry)
type: adr
status: accepted
owner: zoyoong124@gmail.com
last-updated: 2026-07-24
audience: internal
---

# ADR 0003 — 모듈형 크롤 프레임워크

## Status

accepted (백필 — 구조 결정 명문화)

## Context

크롤러는 공지로 시작했지만 학사일정·(예정) 식당처럼 **주기·저장 컬렉션·파싱이 전혀 다른 데이터**가 계속 붙는다. 도메인마다 스케줄링·DB 연결·설정 로드·로깅을 새로 짜면 중복이 쌓인다.

## Decision

**얇은 모듈 계약 하나를 두고, 공통 인프라는 `shared/`로 재사용한다.**

- `CrawlModule` Protocol (`modules/base.py`): `config`(property) + `async run()` + `async shutdown()`. 구조적 타이핑이라 상속 불필요.
- `ModuleConfig` dataclass가 스케줄러에 필요한 최소 정보 선언 (`name`, `collection_name`, `cron_schedule`/`interval_seconds`, `run_on_start`).
- `modules/registry.py` 전역 레지스트리 + 루트 `cli.py`의 APScheduler가 등록된 모든 모듈을 각자 주기로 구동.
- 도메인 모듈은 자기 컬렉션·주기·파싱만 책임지고 `shared/config.py`·`shared/db.py`·`shared/fetcher.py`·`shared/logger.py`를 재사용.

## Consequences

- ✅ 새 도메인 = 모듈 디렉토리 + registry 한 줄 ([how-to/add-a-module.md](../how-to/add-a-module.md)). 인프라 재작성 없음.
- ✅ `notices`(문서=공지)와 `schedule`(문서=학년도+events 배열)처럼 전혀 다른 형태가 한 스케줄러에 공존.
- ✅ **식당 모듈**이 코드·문서상 예측 가능한 자리 확보 (greenfield).
- ⚠️ 규율 필요: 모듈이 `shared/`를 우회해 직접 `os.getenv()`/DB 클라이언트를 만들면 env 라우팅·싱글턴 일관성이 깨진다 ([explanation/module-system.md](../explanation/module-system.md) 안티패턴).
