import 'dotenv/config';
import { runCrawl, type CrawlOptions } from './orchestrator.js';
import { closeClient } from '../shared/db.js';
import logger from '../shared/logger.js';
import { loadAndValidate } from './config/loader.js';

function parseArgs(): {
  once: boolean;
  all: boolean;
  dept?: string;
  pages?: number;
  delay: number;
} {
  const args = process.argv.slice(2);
  const result = {
    once: args.includes('--once'),
    all: args.includes('--all'),
    dept: undefined as string | undefined,
    pages: undefined as number | undefined,
    delay: 500,
  };

  const deptIdx = args.indexOf('--dept');
  if (deptIdx !== -1 && args[deptIdx + 1]) {
    result.dept = args[deptIdx + 1];
  }

  const pagesIdx = args.indexOf('--pages');
  if (pagesIdx !== -1 && args[pagesIdx + 1]) {
    result.pages = parseInt(args[pagesIdx + 1], 10);
  }

  const delayIdx = args.indexOf('--delay');
  if (delayIdx !== -1 && args[delayIdx + 1]) {
    result.delay = parseInt(args[delayIdx + 1], 10);
  }

  return result;
}

async function main(): Promise<void> {
  const args = parseArgs();
  const departments = loadAndValidate();

  const options: CrawlOptions = {
    incremental: !args.all,
    maxPages: args.pages,
    delayMs: args.delay,
    deptFilter: args.dept,
  };

  if (args.once) {
    logger.info({ options }, 'Running one-time crawl');
    const results = await runCrawl(departments, options);

    // Print summary
    for (const r of results) {
      logger.info(
        {
          dept: r.deptName,
          inserted: r.inserted,
          updated: r.updated,
          errors: r.errors,
          duration: `${(r.durationMs / 1000).toFixed(1)}s`,
        },
        'Result'
      );
    }

    await closeClient();
    process.exit(0);
  }

  // Cron mode: run every 30 minutes
  const cron = await import('node-cron');
  logger.info('Starting cron mode — crawling every 30 minutes');

  // Run immediately on start
  await runCrawl(departments, options);

  cron.schedule('*/30 * * * *', async () => {
    logger.info('Cron triggered: starting crawl');
    try {
      await runCrawl(departments, options);
    } catch (err) {
      logger.error({ error: (err as Error).message }, 'Cron crawl failed');
    }
  });

  // Graceful shutdown
  const shutdown = async (signal: string) => {
    logger.info({ signal }, 'Shutting down');
    await closeClient();
    process.exit(0);
  };

  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('SIGINT', () => shutdown('SIGINT'));
}

main().catch((err) => {
  logger.error({ error: err }, 'Fatal error');
  process.exit(1);
});
