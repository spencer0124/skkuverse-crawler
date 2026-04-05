import 'dotenv/config';
import { closeClient } from './shared/db.js';
import logger from './shared/logger.js';
import { runCrawl } from './notices/orchestrator.js';
import { loadAndValidate } from './notices/config/loader.js';

/**
 * Top-level cron scheduler for all crawler modules.
 *
 * Currently runs the notices crawler on a 30-minute cycle.
 * Future modules (meals, library, etc.) will be added here
 * with their own schedules.
 */
async function main(): Promise<void> {
  const cron = await import('node-cron');

  // ── Notices module ──────────────────────────────────
  const departments = loadAndValidate();

  logger.info('Starting cron scheduler');

  // Run all modules immediately on start
  await runCrawl(departments, { incremental: true });

  // Schedule notices crawl every 30 minutes
  cron.schedule('*/30 * * * *', async () => {
    logger.info('Cron triggered: starting notices crawl');
    try {
      await runCrawl(departments, { incremental: true });
    } catch (err) {
      logger.error({ error: (err as Error).message }, 'Notices cron crawl failed');
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
