# skkuverse-crawler

SKKU 관련 데이터 크롤링 + 콘텐츠 정제 서비스.

## Commands

```bash
# Notices 크롤러 (모듈별 직접 실행)
npm run notices              # 1회 실행 (incremental)
npm run notices:all          # 전체 크롤 (non-incremental)
npx tsx src/notices/cli.ts --once --dept skku-main --pages 3  # 단일 학과

# 전체 cron 스케줄러
npm start                    # 모든 모듈 cron 실행

# 유틸리티
npm run verify:selectors     # CSS 셀렉터 검증
npm run backfill:cleanhtml   # cleanHtml 필드 백필
npx tsx scripts/test-cleanhtml.ts  # HTML 정제 테스트
```

## Architecture

모듈형 구조: `src/shared/` (공통 인프라) + `src/notices/` (공지 크롤러 모듈)

- `shared/db.ts` — MongoDB 싱글턴
- `shared/logger.ts` — pino 로거
- `shared/fetcher.ts` — HTTP 클라이언트 (retry + rate-limit)
- `notices/cli.ts` — 모듈 CLI 진입점
- `notices/orchestrator.ts` — p-limit(5) 병렬 크롤 조율
- `notices/strategies/` — 7개 전략 (skku-standard, wordpress-api, skkumed-asp, jsp-dorm, custom-php, gnuboard, gnuboard-custom)
- `notices/config/departments.json` — 133+ 학과 설정

### Key Patterns

- **Strategy Pattern**: `CrawlStrategy` 인터페이스 + departments.json config-driven
- **Incremental Crawl**: title+date 변경 감지, 변경분만 상세 fetch
- **6-step HTML Cleaning**: 모바일 렌더링용 HTML 정제 파이프라인
- **Null Content Recovery**: content:null 기사 자동 재크롤링

## Adding New Modules

향후 `src/meals/`, `src/library/` 등 추가 시:
1. `src/<module>/` 디렉토리 생성
2. 자체 `types.ts`, `config/`, `strategies/` 구성
3. `cli.ts`로 독립 실행 가능하게
4. `src/index.ts`에 cron 스케줄 등록
5. `shared/` 인프라 재사용 (db, logger, fetcher)

## Environment

`.env` 파일 필요 (`.env.example` 참고):
- `MONGO_URL` — MongoDB 연결 문자열
- `MONGO_DB_NAME` — DB 이름 (기본: skku_notices)
- `NODE_ENV` — development/production/test
