---
title: 새 크롤 모듈 추가하기
type: how-to
status: accepted
owner: zoyoong124@gmail.com
last-updated: 2026-07-24
audience: internal
---

# 새 크롤 모듈 추가하기

> 새 데이터 도메인(예: 식당)을 크롤러에 추가하는 절차. 왜 이 패턴인지(프레임워크 배경)는 [explanation/module-system.md](../explanation/module-system.md).

## 개요

각 도메인은 `CrawlModule` Protocol을 구현하는 **독립 모듈**이다. 스케줄링·DB·로깅은 `shared/` 인프라를 재사용하고, 모듈은 자기 컬렉션·주기·파싱만 책임진다.

## 단계

1. **모듈 디렉토리 생성** — `py/src/skkuverse_crawler/<module>/`
   - 최소: `module.py`(`CrawlModule` 구현 + `ModuleConfig`), `models.py`(문서 dataclass), `repository.py` 또는 `dedup.py`(DB 쓰기), 필요 시 `fetcher_parser.py`, `cli.py`
2. **`CrawlModule` Protocol 구현** (`module.py`) — `config`(property), `async run()`, `async shutdown()`. `ModuleConfig(name, collection_name, cron_schedule|interval_seconds, run_on_start)` 선언.
3. **`shared/` 재사용** — `get_config()`, `get_db()[collection_name]`, `shared/fetcher.py`, `shared/logger.py`. 직접 `os.getenv()`/`AsyncIOMotorClient()` 만들지 말 것.
4. **스케줄러에 등록** — 루트 `cli.py`의 `start`에서 `registry.register(<Module>())` 추가. (서브커맨드가 필요하면 모듈 `cli.py`에 `@click.command` 정의 후 루트 `cli.py`에서 `main.add_command`.)
5. **스키마 문서 추가** — `docs/reference/schema/<module>.md` (기존 [notices.md](../reference/schema/notices.md)/[schedule.md](../reference/schema/schedule.md)와 같은 형태). umbrella [data-topology](https://github.com/spencer0124/skkuverse/blob/main/docs/architecture/data-topology.md)에도 컬렉션 행 추가.
6. **테스트 추가** — `py/tests/<module>/` (기존 모듈 테스트 미러). httpx는 `respx`로, DB는 `conftest.py`의 전역 mock 사용.

## 검증

```bash
cd py
python -m skkuverse_crawler <module> --once     # 1회 실행 (모듈 CLI가 있으면)
uv run pytest tests/<module>/ -v
uv run ruff check src/ && uv run mypy src/
```

## 예시 — 전략(strategy) vs 모듈(module)

- **같은 도메인, 다른 사이트 구조** → 새 **전략** (`notices/strategies/`) + `sources.json` 한 줄. 코드 최소.
- **다른 도메인 (다른 컬렉션·주기·파싱)** → 새 **모듈**. 식당은 이쪽 — `notices`가 아니라 `RestaurantModule`.

## 관련 문서

- [explanation/module-system.md](../explanation/module-system.md) — 프레임워크 배경
- [decisions/0003-modular-crawl-framework.md](../decisions/0003-modular-crawl-framework.md)
- [add-a-source.md](add-a-source.md) — 기존 전략으로 소스만 추가할 때
