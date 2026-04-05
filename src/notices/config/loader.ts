import departments from './departments.json';
import type { DepartmentConfig } from '../types.js';
import logger from '../../shared/logger.js';

const REQUIRED_SELECTORS: Record<string, string[]> = {
  'skku-standard': ['listItem', 'category', 'titleLink', 'infoList', 'detailContent', 'attachmentList'],
  'wordpress-api': [], // API-based — no HTML selectors needed
  'skkumed-asp': ['listItem', 'titleLink', 'infoList', 'detailContent', 'attachmentList'],
  'jsp-dorm': ['listRow', 'pinnedRow', 'titleLink', 'detailContent', 'attachmentLink'],
  'custom-php': ['listRow', 'titleLink', 'category', 'views', 'date', 'detailContent'],
  'gnuboard': ['listRow', 'titleLink', 'author', 'date', 'detailContent', 'detailAttachment'],
  'gnuboard-custom': ['listRow', 'titleLink', 'date', 'meta', 'detailContent', 'detailAttachment'],
};

export function loadAndValidate(): DepartmentConfig[] {
  const configs = departments as unknown as DepartmentConfig[];
  const errors: string[] = [];

  for (const dept of configs) {
    const required = REQUIRED_SELECTORS[dept.strategy];
    if (!required) {
      errors.push(`${dept.id}: unknown strategy "${dept.strategy}"`);
      continue;
    }

    if (required.length === 0) continue; // API-based strategies don't need selectors

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const selectors = (dept as any).selectors as Record<string, string> | undefined;
    if (!selectors) {
      errors.push(`${dept.id}: missing selectors object`);
      continue;
    }

    for (const sel of required) {
      if (!(sel in selectors)) {
        errors.push(`${dept.id}: missing selector "${sel}" for strategy "${dept.strategy}"`);
      }
    }
  }

  // Check for duplicate IDs
  const ids = configs.map((c) => c.id);
  const seen = new Set<string>();
  const dupes: string[] = [];
  for (const id of ids) {
    if (seen.has(id)) dupes.push(id);
    seen.add(id);
  }

  if (dupes.length > 0) {
    errors.push(`Duplicate department IDs: ${dupes.join(', ')}`);
  }

  if (errors.length > 0) {
    for (const err of errors) {
      logger.error(err);
    }
    logger.error({ count: errors.length }, 'Config validation failed');
    process.exit(1);
  }

  logger.info({ count: configs.length }, 'Loaded department configs');
  return configs;
}
