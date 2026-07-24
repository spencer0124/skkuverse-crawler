---
title: 모듈 시스템
type: explanation
status: accepted
owner: zoyoong124@gmail.com
last-updated: 2026-07-24
audience: internal
---

# 모듈 시스템

> 크롤러가 "공지 크롤러"가 아니라 **여러 데이터 도메인을 담는 프레임워크**인 이유와 구조. 새 도메인(학사일정, 그리고 예정된 식당)이 같은 계약으로 꽂히는 메커니즘. 실제 추가 절차(런북)는 [how-to/add-a-module.md](../how-to/add-a-module.md).

## 문제 — 왜 프레임워크인가

크롤러는 처음엔 공지만 긁었지만, 학사일정·(예정) 식당처럼 **주기·저장 컬렉션·파싱이 전혀 다른 데이터**가 계속 붙는다. 이걸 매번 새 스크립트로 만들면 스케줄링·DB 연결·로깅·설정 로드가 도메인마다 중복된다. 그래서 **얇은 모듈 계약** 하나를 두고, 공통 인프라(`shared/`)는 재사용하게 했다.

## 계약 — `CrawlModule` Protocol

`modules/base.py`. 구조적 타이핑(Protocol)이라 모듈은 이 인터페이스를 **상속 없이** 만족하면 된다:

```python
@runtime_checkable
class CrawlModule(Protocol):
    @property
    def config(self) -> ModuleConfig: ...
    async def run(self, incremental: bool = True, **kwargs) -> dict: ...
    async def shutdown(self) -> None: ...
```

`ModuleConfig` (dataclass)가 스케줄러에게 필요한 최소 정보를 선언한다:

| 필드 | 의미 |
| --- | --- |
| `name` | 모듈 식별자 (registry 키, `--module` 값) |
| `collection_name` | 이 모듈이 쓰는 MongoDB 컬렉션 |
| `cron_schedule` | cron 문자열 (또는 `interval_seconds`) |
| `interval_seconds` | 주기 초 (cron 대신) |
| `run_on_start` | 부팅 시 즉시 1회 실행 여부 |

## 등록 — registry

`modules/registry.py`는 이름→모듈의 전역 dict다. `register(module)`이 `module.config.name`으로 저장하고, 스케줄러(`cli.py`의 `start`)가 `all_modules()`를 돌며 각 모듈의 `config`대로 APScheduler job을 건다. `--module <name>`은 `get_module(name)` 하나만 스케줄링한다.

```
cli.py start
  → registry.register(NoticesModule())        # 각 모듈 등록
  → registry.register(NoticesUpdateCheckModule())
  → registry.register(NoticesSummaryModule())
  → registry.register(ScheduleModule())
  → all_modules() 순회 → ModuleConfig.cron_schedule 대로 mod.run() 스케줄
```

## 이 설계가 사는 곳 — 확장성

새 도메인을 추가할 때 건드리는 것은 **자기 모듈 디렉토리 + 한 줄 등록**뿐이다. 공통 인프라는 그대로 재사용한다:

- `shared/config.py` — 환경·DB 라우팅
- `shared/db.py` — Motor 싱글턴 (`get_db()[collection_name]`)
- `shared/fetcher.py` · `shared/logger.py` — HTTP 재시도 · 구조화 로깅

**예시 — 두 도메인의 대비:**

| | notices | schedule |
| --- | --- | --- |
| 컬렉션 | `notices` (문서=공지 1건) | `schedule` (문서=학년도 1개, events 배열) |
| 주기 | `*/30` | `30 5 * * *` (+ `run_on_start`) |
| 파싱 | Strategy Pattern (9종, config-driven) | 단일 파서 |
| upsert 키 | `(articleNo, sourceId)` | `_id = 학년도` (자연키, hash 게이트) |

전혀 다른 두 도메인이 같은 `CrawlModule` 계약으로 한 스케줄러에 공존한다. **식당 모듈**도 이 패턴을 그대로 따른다 — 자기 컬렉션·주기·파서를 가진 `RestaurantModule`을 만들고 registry에 등록하면 끝. 근거는 [ADR 0003](../decisions/0003-modular-crawl-framework.md).

## 안티패턴

- 모듈 안에서 직접 `os.getenv()` / `AsyncIOMotorClient()` 만들기 → **금지**. `shared/config.py` · `shared/db.py`만 거친다 (env 라우팅·싱글턴 일관성).
- 도메인 로직을 `shared/`에 넣기 → `shared/`는 도메인 무관 인프라만. 도메인 지식은 모듈 안에.

## 관련 문서

- [how-to/add-a-module.md](../how-to/add-a-module.md) — 실제 추가 절차 (런북)
- [architecture.md](architecture.md) — 전체 구조
- [decisions/0003-modular-crawl-framework.md](../decisions/0003-modular-crawl-framework.md)
