# ADR-004: MCP 서버 — 크롤러 레포 내 모듈, fastmcp, 익명 공개 HTTP

- **상태**: **대체됨** (2026-07-29, 당일 개정) — 배치 결론이 `skkuverse-ai/docs/decisions/adr-001-ai-gateway-embed-mcp.md`로 대체됨
- **관련**: [adr-003](adr-003-hybrid-search-atlas.md)

> [!IMPORTANT]
> **대체 사유**: 이 ADR 확정 직후 새 제약이 확인됨 — **skkuverse-crawler는 오픈소스 공개 예정**(범용 SKKU 크롤링 엔진). 벤더 키·제품용 공개 MCP 서버는 OSS 목표와 충돌하므로, MCP 서버·임베딩 API·검색 질의 측은 **skkuverse-ai**(이미 모델 벤더 접점: litellm Router·API 키·`/api/notices/summarize`)로 이관. 크롤러는 `notices_embedding` 오케스트레이션(요약 모듈과 동일 분업: stale 감지 + ai `/api/embed` 호출 + `$set`)만 유지. 부수 효과: 모든 임베딩 호출이 한 엔드포인트를 거치므로 "세 소비자 모델 드리프트" 리스크가 구조적으로 소멸. SDK(fastmcp)·transport(stateless HTTP)·익명 공개 + rate limit 결론은 새 배치에서도 그대로 유효하다.
> 아래 원문은 당시 판단 기록으로 보존. **"배치" 섹션의 비교표는 OSS 계획을 모르던 시점의 분석**임에 유의.

## 맥락

크롤링·정제된 SKKU 데이터를 MCP(Model Context Protocol) 서버로 공개해, 누구나 URL을 MCP 클라이언트(claude.ai 커스텀 커넥터, Claude Code 등)에 등록하면 질의할 수 있게 한다. 결정할 것: ① 어느 레포에 둘 것인가 ② 어떤 SDK ③ 접근 방식.

## 결정

1. **배치: 크롤러 레포 내 `mcp_server/` 모듈** (`python -m skkuverse_crawler mcp` 서브커맨드, docker-compose에 서비스 추가)
2. **SDK: `fastmcp` 3.x** (`>=3.4,<4`)
3. **접근: streamable HTTP + 익명(무인증) 공개**, 단 read-only 3중 방어 + per-IP rate limit

## 근거

### 배치 — "MCP 서버는 얇은 어댑터, 감쌀 대상 옆에 둔다"

| 옵션 | 판단 |
|------|------|
| **크롤러 레포 내 모듈 (채택)** | 스키마 SSOT(`models.py`, `sources.json`)·`shared/db.py`·config·검색 공유 모듈이 전부 이 레포에 있음 → 재사용 최대, 스키마 드리프트 원천 차단. 기존 compose에 서비스 1개 추가로 배포 끝 |
| 별도 레포 | 배포 독립성은 얻지만 DB 레이어·모델을 복사(=드리프트 시작)하거나 크롤러를 패키지로 배포해야 함. GitHub/Notion식 별도 레포 관행은 "이미 public API가 있어 그걸 감싸는" 경우의 이야기 — 여긴 내부 DB 직결 |
| skkuverse-server(NestJS)에 추가 | TypeScript SDK로 재구현 필요 — Python 모델·검색 파이프라인 재사용 불가. 서버 역할(앱 API + FCM) 비대화 |

외부 공개 규모가 커지면 그때 분리 — fastmcp는 transport 전환이 코드 무변경이라 이전 비용이 낮다.

### SDK

- 공식 `mcp` Python SDK는 2026-07-28 **v2.0 breaking 릴리스 직후** — 1.x는 이미 구세대, 2.0은 출시 하루째. 어느 쪽이든 churn 리스크.
- `fastmcp` 3.x는 내부적으로 `mcp<2`를 핀해 절연 + 이 서버가 필요로 하는 것 전부 내장: stateless streamable HTTP, `RateLimitingMiddleware`(per-client 훅), `/health` custom route, **인메모리 테스트 Client** (기존 pytest 체계에 소켓 없이 통합).

### 접근 방식

- 데이터가 공개 대학 공지라 노출 민감도 낮음 → 익명 허용. 대신:
  1. **Atlas read-only 유저** (`MONGO_URL_MCP`) — 하드 보장. read 롤로 `$search`/`$vectorSearch` 쿼리는 가능(인덱스 생성만 readWrite 필요)
  2. 코드 경로 분리 — `shared/db.py`에 병렬 싱글턴 `get_mcp_db()`, 쿼리는 find/aggregate만
  3. per-IP rate limit (기본 2rps/burst 10) + 응답 프로젝션으로 내부 필드(`content`, `contentText`, `editHistory`, `aiSummaryAt`, `contentEmbedding` 등) 절대 미노출
- stateless HTTP: 세션 어피니티 불필요, 임의 프록시 뒤 안전, 추후 워커 확장 허용.

## 재검토 조건

- 남용(스크래핑·쿼터 소진) 발생 → OAuth/토큰 도입
- 공식 `mcp` SDK 2.x 안정화 + fastmcp 유지보수 이슈 → SDK 재평가
- MCP 소비자가 커져 배포 주기가 크롤러와 충돌 → 별도 레포/서비스 분리
