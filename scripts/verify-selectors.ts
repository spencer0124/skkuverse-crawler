/**
 * Selector Verification Script
 *
 * Fetches the first list page for each department in departments.json
 * and verifies that configured CSS selectors match elements.
 *
 * Usage:
 *   npx tsx scripts/verify-selectors.ts [--delay 2000] [--dept <id>]
 */

import 'dotenv/config';
import axios from 'axios';
import * as cheerio from 'cheerio';
import { loadAndValidate } from '../src/notices/config/loader.js';
import type { SkkuStandardDepartmentConfig } from '../src/notices/types.js';

interface VerifyResult {
  id: string;
  name: string;
  url: string;
  status: 'OK' | 'WARN' | 'FAIL';
  listItems: number;
  hasTitle: boolean;
  hasArticleNo: boolean;
  hasInfoList: boolean;
  hasDetailContent: boolean | null; // null = not tested
  error?: string;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseArgs() {
  const args = process.argv.slice(2);
  let delay = 2000;
  let dept: string | undefined;

  const delayIdx = args.indexOf('--delay');
  if (delayIdx !== -1 && args[delayIdx + 1]) {
    delay = parseInt(args[delayIdx + 1], 10);
  }

  const deptIdx = args.indexOf('--dept');
  if (deptIdx !== -1 && args[deptIdx + 1]) {
    dept = args[deptIdx + 1];
  }

  return { delay, dept };
}

async function fetchPage(url: string): Promise<string> {
  const resp = await axios.get<string>(url, {
    timeout: 15_000,
    headers: {
      'User-Agent': 'Mozilla/5.0 (compatible; SKKUverseCrawler/1.0)',
    },
    responseType: 'text',
  });
  return resp.data;
}

async function verifyDepartment(config: SkkuStandardDepartmentConfig): Promise<VerifyResult> {
  const result: VerifyResult = {
    id: config.id,
    name: config.name,
    url: config.baseUrl,
    status: 'FAIL',
    listItems: 0,
    hasTitle: false,
    hasArticleNo: false,
    hasInfoList: false,
    hasDetailContent: null,
  };

  try {
    // Build list URL (page 0)
    const extra = config.extraParams
      ? Object.entries(config.extraParams).map(([k, v]) => `${k}=${v}`).join('&') + '&'
      : '';
    const url = `${config.baseUrl}?${extra}mode=list&articleLimit=${config.pagination.limit}&${config.pagination.param}=0`;

    const html = await fetchPage(url);
    const $ = cheerio.load(html);

    // Check list items
    const $items = $(config.selectors.listItem);
    result.listItems = $items.length;

    if ($items.length > 0) {
      const $first = $items.first();

      // Check title link
      const $titleLink = $first.find(config.selectors.titleLink);
      result.hasTitle = $titleLink.length > 0 && $titleLink.text().trim().length > 0;

      // Check articleNo extraction (standard: articleNo, Type H: itemId)
      const href = $titleLink.attr('href') || '';
      result.hasArticleNo = /articleNo=\d+/.test(href) || /itemId=\d+/.test(href);

      // Check info list
      const $info = $first.find(config.selectors.infoList);
      result.hasInfoList = $info.length >= 3; // need at least author, date, views
    }

    // Determine status
    if (result.listItems > 0 && result.hasTitle && result.hasArticleNo) {
      result.status = result.hasInfoList ? 'OK' : 'WARN';
    } else if (result.listItems > 0) {
      result.status = 'WARN';
    }
  } catch (err) {
    result.error = (err as Error).message?.slice(0, 80);
  }

  return result;
}

async function main() {
  const { delay, dept } = parseArgs();
  const departments = loadAndValidate();

  let targets = departments.filter((d) => d.strategy === 'skku-standard') as SkkuStandardDepartmentConfig[];
  if (dept) {
    targets = targets.filter((d) => d.id === dept);
  }

  console.log(`\nVerifying ${targets.length} departments (delay: ${delay}ms)\n`);
  console.log(
    'ID'.padEnd(30) +
    'Items'.padEnd(7) +
    'Title'.padEnd(7) +
    'ArtNo'.padEnd(7) +
    'Info'.padEnd(7) +
    'Status'.padEnd(8) +
    'Error'
  );
  console.log('-'.repeat(90));

  const results: VerifyResult[] = [];

  for (const config of targets) {
    const r = await verifyDepartment(config);
    results.push(r);

    const statusColor = r.status === 'OK' ? '\u2705' : r.status === 'WARN' ? '\u26a0\ufe0f' : '\u274c';
    console.log(
      r.id.padEnd(30) +
      String(r.listItems).padEnd(7) +
      (r.hasTitle ? 'Y' : 'N').padEnd(7) +
      (r.hasArticleNo ? 'Y' : 'N').padEnd(7) +
      (r.hasInfoList ? 'Y' : 'N').padEnd(7) +
      `${statusColor} ${r.status}`.padEnd(8) +
      (r.error || '')
    );

    if (targets.indexOf(config) < targets.length - 1) {
      await sleep(delay);
    }
  }

  // Summary
  const ok = results.filter((r) => r.status === 'OK').length;
  const warn = results.filter((r) => r.status === 'WARN').length;
  const fail = results.filter((r) => r.status === 'FAIL').length;
  console.log(`\n--- Summary: ${ok} OK, ${warn} WARN, ${fail} FAIL (total: ${results.length}) ---\n`);

  if (fail > 0) {
    console.log('Failed departments:');
    for (const r of results.filter((r) => r.status === 'FAIL')) {
      console.log(`  ${r.id}: ${r.error || 'no items found'}`);
    }
  }
}

main().catch((err) => {
  console.error('Fatal:', err);
  process.exit(1);
});
