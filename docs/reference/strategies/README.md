---
title: 크롤 전략 인덱스
type: reference
status: accepted
owner: zoyoong124@gmail.com
last-updated: 2026-07-24
audience: internal
---

# 크롤 전략 인덱스

> 각 전략은 특정 게시판 종류의 DOM 구조·셀렉터·페이지네이션을 캡슐화한다. 전략은 `sources.json`의 `strategy` 필드로 소스에 배정된다 (config-driven — [ADR 0002](../../decisions/0002-config-driven-strategy-pattern.md)). 어떤 소스가 어떤 전략을 쓰는지의 **분포는 codegen이 SSOT** → [coverage](../coverage/department-coverage-analysis.md) (개수 박제 금지).

| 전략 문서 | 대상 |
| --- | --- |
| [strategy-skku-standard.md](strategy-skku-standard.md) | 표준 `www.skku.edu` 게시판 (대다수 학과) |
| [strategy-gnuboard.md](strategy-gnuboard.md) | gnuboard 계열 PHP 게시판 |
| [strategy-custom-php.md](strategy-custom-php.md) | custom-php (cal.skku.edu) |
| [strategy-wordpress.md](strategy-wordpress.md) | wordpress-api (cheme) |
| [strategy-asp.md](strategy-asp.md) | skkumed-asp (의과대학, EUC-KR) |
| [strategy-jsp-dorm.md](strategy-jsp-dorm.md) | jsp-dorm (기숙사 게시판) |
| [strategy-chem-nonstandard.md](strategy-chem-nonstandard.md) | 화학과 비표준 게시판 |

> [!NOTE]
> 정리 예정(follow-up): `strategy-custom-php.md`와 `strategy-gnuboard.md`가 cal.skku.edu custom-php를 중복 문서화하고, `strategy-custom-php.md`에는 2026-04-10 PR 포스트모템이 섞여 있다 — 후자는 `internal/`로 분리 대상.

## 전략 구현 코드

전략 구현은 `notices/strategies/`에 있다 (`base.py` + 전략별 파일). 전략별 기능 도출(`hasCategory`/`hasAuthor`)은 `generate_artifacts.py`의 `STRATEGY_FEATURES`.

## 관련 문서

- [reference/schema/notices.md](../schema/notices.md) — 전략이 채우는 필드
- [decisions/0002-config-driven-strategy-pattern.md](../../decisions/0002-config-driven-strategy-pattern.md)
