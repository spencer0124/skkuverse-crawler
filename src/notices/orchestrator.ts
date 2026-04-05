import { Collection } from 'mongodb';
import type { Logger } from 'pino';
import { getDb } from '../shared/db.js';
import { Fetcher } from '../shared/fetcher.js';
import { Notice, NoticeListItem, buildNotice } from './normalizer.js';
import { cleanHtml } from './cleanHtml.js';
import {
  ensureIndexes, findExistingMeta, hasChanged, shouldContinue,
  upsertNotice, bulkTouchNotices, findNullContent,
  type ExistingMeta,
} from './dedup.js';
import { SkkuStandardStrategy } from './strategies/skku-standard.js';
import { WordPressApiStrategy } from './strategies/wordpress-api.js';
import { SkkumedAspStrategy } from './strategies/skkumed-asp.js';
import { JspDormStrategy } from './strategies/jsp-dorm.js';
import { CustomPhpStrategy } from './strategies/custom-php.js';
import { GnuboardStrategy } from './strategies/gnuboard.js';
import { GnuboardCustomStrategy } from './strategies/gnuboard-custom.js';
import type { DepartmentConfig, CrawlStrategy } from './types.js';
import { randomUUID } from 'node:crypto';
import baseLogger from '../shared/logger.js';

export interface CrawlOptions {
  incremental: boolean;
  maxPages?: number;
  delayMs?: number;
  deptFilter?: string;
}

interface DeptResult {
  deptId: string;
  deptName: string;
  inserted: number;
  updated: number;
  skipped: number;
  errors: number;
  durationMs: number;
}

const strategyMap: Record<string, (fetcher: Fetcher) => CrawlStrategy> = {
  'skku-standard': (fetcher) => new SkkuStandardStrategy(fetcher),
  'wordpress-api': (fetcher) => new WordPressApiStrategy(fetcher),
  'skkumed-asp': (fetcher) => new SkkumedAspStrategy(fetcher),
  'jsp-dorm': (fetcher) => new JspDormStrategy(fetcher),
  'custom-php': (fetcher) => new CustomPhpStrategy(fetcher),
  'gnuboard': (fetcher) => new GnuboardStrategy(fetcher),
  'gnuboard-custom': (fetcher) => new GnuboardCustomStrategy(fetcher),
};

export async function runCrawl(
  departments: DepartmentConfig[],
  options: CrawlOptions
): Promise<DeptResult[]> {
  const crawlId = randomUUID().slice(0, 8);
  const logger = baseLogger.child({ crawlId });

  const db = await getDb();
  const collection = db.collection<Notice>('notices');
  await ensureIndexes(collection);

  const pLimit = (await import('p-limit')).default;
  const limit = pLimit(5);

  const fetcher = new Fetcher({ delayMs: options.delayMs });

  const filtered = options.deptFilter
    ? departments.filter((d) => d.id === options.deptFilter)
    : departments;

  if (filtered.length === 0) {
    logger.warn({ deptFilter: options.deptFilter }, 'No matching departments found');
    return [];
  }

  const tasks = filtered.map((dept) =>
    limit(() => crawlDepartment(dept, collection, fetcher, options, logger))
  );

  const results = await Promise.allSettled(tasks);

  const deptResults: DeptResult[] = [];
  for (const r of results) {
    if (r.status === 'fulfilled') {
      deptResults.push(r.value);
    } else {
      logger.error({ error: r.reason }, 'Department crawl failed');
    }
  }

  const totalInserted = deptResults.reduce((s, r) => s + r.inserted, 0);
  const totalUpdated = deptResults.reduce((s, r) => s + r.updated, 0);
  const totalSkipped = deptResults.reduce((s, r) => s + r.skipped, 0);
  const totalErrors = deptResults.reduce((s, r) => s + r.errors, 0);
  logger.info(
    { departments: deptResults.length, totalInserted, totalUpdated, totalSkipped, totalErrors },
    'Crawl completed'
  );

  return deptResults;
}

async function crawlDepartment(
  dept: DepartmentConfig,
  collection: Collection<Notice>,
  fetcher: Fetcher,
  options: CrawlOptions,
  logger: Logger
): Promise<DeptResult> {
  const start = Date.now();
  const strategyFactory = strategyMap[dept.strategy];
  if (!strategyFactory) {
    throw new Error(`Unknown strategy: ${dept.strategy}`);
  }

  const strategy = strategyFactory(fetcher);
  const result: DeptResult = {
    deptId: dept.id,
    deptName: dept.name,
    inserted: 0,
    updated: 0,
    skipped: 0,
    errors: 0,
    durationMs: 0,
  };

  logger.info({ deptId: dept.id, deptName: dept.name }, 'Starting department crawl');

  // Re-crawl previously failed detail pages (content: null)
  const nullContentRefs = await findNullContent(collection, dept.id);
  if (nullContentRefs.length > 0) {
    logger.info({ count: nullContentRefs.length, deptId: dept.id }, 'Re-crawling null content articles');
    for (const ref of nullContentRefs) {
      const detail = await strategy.crawlDetail(ref, dept);
      if (detail) {
        await collection.updateOne(
          { articleNo: ref.articleNo, sourceDeptId: dept.id },
          {
            $set: {
              content: detail.content,
              contentText: detail.contentText,
              cleanHtml: cleanHtml(detail.content, dept.baseUrl),
              attachments: detail.attachments,
              crawledAt: new Date(),
            },
          }
        );
        result.updated++;
      }
    }
  }

  // Crawl list pages
  const maxPages = options.maxPages ?? (options.incremental ? 100 : 2500);
  let page = 0;

  while (page < maxPages) {
    let listItems: NoticeListItem[];
    try {
      listItems = await strategy.crawlList(dept, page);
    } catch (err) {
      logger.error({ deptId: dept.id, page, error: (err as Error).message }, 'Failed to fetch list page');
      result.errors++;
      break;
    }

    if (listItems.length === 0) {
      logger.info({ deptId: dept.id, page }, 'Empty list page — end of notices');
      break;
    }

    const isFirstPage = page === 0;

    if (options.incremental) {
      const articleNos = listItems.map((item) => item.articleNo);
      const existingMeta = await findExistingMeta(collection, dept.id, articleNos);
      const allKnown = !shouldContinue(listItems, existingMeta);

      if (!isFirstPage && allKnown) {
        logger.info({ page }, 'All items already in DB — stopping pagination');
        break;
      }

      if (isFirstPage && allKnown) {
        logger.info('All items on page 1 already in DB — early stop');
        await processPageSmart(listItems, existingMeta, strategy, dept, collection, result, logger);
        break;
      }

      await processPageSmart(listItems, existingMeta, strategy, dept, collection, result, logger);
    } else {
      await processPageFull(listItems, strategy, dept, collection, result, logger);
    }

    page++;
  }

  result.durationMs = Date.now() - start;
  logger.info(
    { ...result },
    'Department crawl finished'
  );
  return result;
}

async function processPageSmart(
  listItems: NoticeListItem[],
  existingMeta: Map<number, ExistingMeta>,
  strategy: CrawlStrategy,
  dept: DepartmentConfig,
  collection: Collection<Notice>,
  result: DeptResult,
  logger: Logger
): Promise<void> {
  const toTouch: { articleNo: number; sourceDeptId: string; views: number }[] = [];

  for (const item of listItems) {
    try {
      const existing = existingMeta.get(item.articleNo);

      if (existing && !hasChanged(item, existing)) {
        toTouch.push({ articleNo: item.articleNo, sourceDeptId: dept.id, views: item.views });
        result.skipped++;
        continue;
      }

      if (existing) {
        logger.info(
          { articleNo: item.articleNo, oldTitle: existing.title, newTitle: item.title },
          'Change detected — re-fetching detail'
        );
      }

      const detail = await strategy.crawlDetail({ articleNo: item.articleNo, detailPath: item.detailPath }, dept);
      const notice = buildNotice(item, detail, {
        department: dept.name,
        sourceDeptId: dept.id,
        baseUrl: dept.baseUrl,
      });

      const action = await upsertNotice(collection, notice);
      if (action === 'inserted') result.inserted++;
      else result.updated++;
    } catch (err) {
      logger.error(
        { articleNo: item.articleNo, error: (err as Error).message },
        'Failed to process article'
      );
      result.errors++;
    }
  }

  if (toTouch.length > 0) {
    await bulkTouchNotices(collection, toTouch);
  }
}

async function processPageFull(
  listItems: NoticeListItem[],
  strategy: CrawlStrategy,
  dept: DepartmentConfig,
  collection: Collection<Notice>,
  result: DeptResult,
  logger: Logger
): Promise<void> {
  for (const item of listItems) {
    try {
      const detail = await strategy.crawlDetail({ articleNo: item.articleNo, detailPath: item.detailPath }, dept);
      const notice = buildNotice(item, detail, {
        department: dept.name,
        sourceDeptId: dept.id,
        baseUrl: dept.baseUrl,
      });

      const action = await upsertNotice(collection, notice);
      if (action === 'inserted') result.inserted++;
      else result.updated++;
    } catch (err) {
      logger.error(
        { articleNo: item.articleNo, error: (err as Error).message },
        'Failed to process article'
      );
      result.errors++;
    }
  }
}
