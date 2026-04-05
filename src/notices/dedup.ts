import { Collection } from 'mongodb';
import { Notice, NoticeListItem } from './normalizer.js';

/**
 * Ensures unique compound index on { articleNo, sourceDeptId }.
 */
export async function ensureIndexes(collection: Collection<Notice>): Promise<void> {
  await collection.createIndex(
    { articleNo: 1, sourceDeptId: 1 },
    { unique: true }
  );
}

/**
 * Stored metadata for an existing notice, used for change detection.
 */
export interface ExistingMeta {
  articleNo: number;
  title: string;
  date: string;
}

/**
 * Fetches existing notices' metadata for change detection.
 * Returns a Map keyed by articleNo.
 */
export async function findExistingMeta(
  collection: Collection<Notice>,
  sourceDeptId: string,
  articleNos: number[]
): Promise<Map<number, ExistingMeta>> {
  const docs = await collection
    .find(
      { sourceDeptId, articleNo: { $in: articleNos } },
      { projection: { articleNo: 1, title: 1, date: 1 } }
    )
    .toArray();
  const map = new Map<number, ExistingMeta>();
  for (const d of docs) {
    map.set(d.articleNo, { articleNo: d.articleNo, title: d.title, date: d.date });
  }
  return map;
}

/**
 * Determines if a list item has changed compared to the DB version.
 * Compares title and date — views excluded (changes constantly).
 */
export function hasChanged(item: NoticeListItem, existing: ExistingMeta): boolean {
  return item.title !== existing.title || item.date !== existing.date;
}

/**
 * Determines if crawling should continue to the next page.
 *
 * Incremental crawl logic:
 * - Page 1 is always processed (but only changed items get detail-fetched).
 * - If ALL items on a page already exist in DB → stop (early stop).
 * - If any new item exists → continue to next page.
 */
export function shouldContinue(
  pageItems: NoticeListItem[],
  existingMeta: Map<number, ExistingMeta>,
): boolean {
  return !pageItems.every((item) => existingMeta.has(item.articleNo));
}

/**
 * Upserts a notice into the collection.
 * Returns 'inserted' | 'updated'.
 */
export async function upsertNotice(
  collection: Collection<Notice>,
  notice: Notice
): Promise<'inserted' | 'updated'> {
  const result = await collection.updateOne(
    { articleNo: notice.articleNo, sourceDeptId: notice.sourceDeptId },
    { $set: notice },
    { upsert: true }
  );

  if (result.upsertedCount > 0) return 'inserted';
  return 'updated';
}

/**
 * Batch update views + crawledAt for unchanged notices.
 * Single bulkWrite instead of N individual updateOne calls.
 */
export async function bulkTouchNotices(
  collection: Collection<Notice>,
  items: { articleNo: number; sourceDeptId: string; views: number }[]
): Promise<void> {
  if (items.length === 0) return;
  const now = new Date();
  const ops = items.map((item) => ({
    updateOne: {
      filter: { articleNo: item.articleNo, sourceDeptId: item.sourceDeptId },
      update: { $set: { views: item.views, crawledAt: now } },
    },
  }));
  await collection.bulkWrite(ops, { ordered: false });
}

/**
 * Finds notices with content: null for re-crawling.
 * Returns articleNo + detailPath for URL construction.
 */
export async function findNullContent(
  collection: Collection<Notice>,
  sourceDeptId: string
): Promise<{ articleNo: number; detailPath: string }[]> {
  const docs = await collection
    .find(
      { sourceDeptId, $or: [{ content: null }, { content: '' }] },
      { projection: { articleNo: 1, detailPath: 1 } }
    )
    .toArray();
  return docs.map((d) => ({
    articleNo: d.articleNo,
    detailPath: d.detailPath || '',
  }));
}
