/**
 * Backfill cleanHtml for existing notices that have content but no cleanHtml.
 *
 * Usage:
 *   npx tsx scripts/backfill-cleanhtml.ts                    # all departments
 *   npx tsx scripts/backfill-cleanhtml.ts --dept skku-main   # single dept
 *   npx tsx scripts/backfill-cleanhtml.ts --batch 50         # smaller batches
 *   npx tsx scripts/backfill-cleanhtml.ts --dry-run          # preview only
 */
import 'dotenv/config';
import { getDb, closeClient } from '../src/shared/db.js';
import { cleanHtml } from '../src/notices/cleanHtml.js';
import { loadAndValidate } from '../src/notices/config/loader.js';
import type { Notice } from '../src/notices/normalizer.js';

function parseArgs() {
  const args = process.argv.slice(2);
  const dryRun = args.includes('--dry-run');
  const deptIdx = args.indexOf('--dept');
  const deptFilter = deptIdx !== -1 ? args[deptIdx + 1] : undefined;
  const batchIdx = args.indexOf('--batch');
  const batchSize = batchIdx !== -1 ? parseInt(args[batchIdx + 1], 10) : 100;
  return { dryRun, deptFilter, batchSize };
}

async function main() {
  const { dryRun, deptFilter, batchSize } = parseArgs();

  // Build sourceDeptId → baseUrl map
  const departments = loadAndValidate();
  const baseUrlMap = new Map<string, string>();
  for (const dept of departments) {
    baseUrlMap.set(dept.id, dept.baseUrl);
  }

  const db = await getDb();
  const collection = db.collection<Notice>('notices');

  const filter: Record<string, unknown> = {
    cleanHtml: { $exists: false },
    content: { $nin: [null, ''] },
  };
  if (deptFilter) {
    filter.sourceDeptId = deptFilter;
  }

  const total = await collection.countDocuments(filter);
  console.log(`Found ${total} notices to backfill${dryRun ? ' (dry run)' : ''}`);

  if (total === 0) {
    await closeClient();
    return;
  }

  let processed = 0;
  let updated = 0;
  let failed = 0;

  const cursor = collection.find(filter, {
    projection: { articleNo: 1, sourceDeptId: 1, content: 1 },
  });

  let batch: { updateOne: { filter: Record<string, unknown>; update: Record<string, unknown> } }[] = [];

  for await (const doc of cursor) {
    const baseUrl = baseUrlMap.get(doc.sourceDeptId);
    if (!baseUrl) {
      console.warn(`No baseUrl for sourceDeptId: ${doc.sourceDeptId}, articleNo: ${doc.articleNo}`);
      failed++;
      continue;
    }

    const cleaned = cleanHtml(doc.content!, baseUrl);
    batch.push({
      updateOne: {
        filter: { articleNo: doc.articleNo, sourceDeptId: doc.sourceDeptId },
        update: { $set: { cleanHtml: cleaned } },
      },
    });

    if (batch.length >= batchSize) {
      if (!dryRun) {
        await collection.bulkWrite(batch, { ordered: false });
      }
      updated += batch.length;
      processed += batch.length;
      console.log(`Progress: ${processed}/${total} (${((processed / total) * 100).toFixed(1)}%)`);
      batch = [];
    }
  }

  // Flush remaining batch
  if (batch.length > 0) {
    if (!dryRun) {
      await collection.bulkWrite(batch, { ordered: false });
    }
    updated += batch.length;
    processed += batch.length;
  }

  console.log(`\nDone. Processed: ${processed}, Updated: ${updated}, Failed: ${failed}`);
  await closeClient();
}

main().catch((err) => {
  console.error('Fatal:', err);
  process.exit(1);
});
