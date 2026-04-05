import { Fetcher } from '../../shared/fetcher.js';
import { loadHtml } from '../parser.js';
import { NoticeListItem, NoticeDetail } from '../normalizer.js';
import type { CustomPhpDepartmentConfig, CrawlStrategy, DetailRef } from '../types.js';
import logger from '../../shared/logger.js';

export class CustomPhpStrategy implements CrawlStrategy {
  private fetcher: Fetcher;

  constructor(fetcher: Fetcher) {
    this.fetcher = fetcher;
  }

  async crawlList(config: CustomPhpDepartmentConfig, page: number): Promise<NoticeListItem[]> {
    const pgNum = page + 1; // 0-based → 1-based
    const boardParamsStr = Object.entries(config.boardParams)
      .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
      .join('&');
    const url = `${config.baseUrl}?${boardParamsStr}&pg=${pgNum}&page=list`;

    logger.info({ url, page }, 'Fetching custom-php list page');
    const html = await this.fetcher.fetch(url);
    const $ = loadHtml(html);

    const items: NoticeListItem[] = [];

    $(config.selectors.listRow).each((_i, el) => {
      try {
        const $tr = $(el);
        const $tds = $tr.find('td');
        if ($tds.length < 2) return; // skip header or malformed rows

        // Title + link from configured selector
        const $titleLink = $tr.find(config.selectors.titleLink);
        const title = $titleLink.text().trim();
        if (!title) return; // skip empty rows (e.g. header)

        const href = $titleLink.attr('href') || '';

        // Extract articleNo via idx=(\d+) from href
        const articleNoMatch = href.match(/idx=(\d+)/);
        if (!articleNoMatch) {
          logger.warn({ href, title }, 'Could not extract idx from custom-php href');
          return;
        }
        const articleNo = parseInt(articleNoMatch[1], 10);

        // Category from configured selector
        const category = $tr.find(config.selectors.category).text().trim();

        // Views from configured selector
        const viewsText = $tr.find(config.selectors.views).text().trim();
        const viewsMatch = viewsText.match(/(\d+)/);
        const views = viewsMatch ? parseInt(viewsMatch[1], 10) : 0;

        // Date from configured selector
        const date = $tr.find(config.selectors.date).text().trim();

        items.push({
          articleNo,
          title,
          category,
          author: '',  // Author not available in list view
          date,
          views,
          detailPath: href,
        });
      } catch (err) {
        logger.warn({ error: (err as Error).message }, 'Failed to parse custom-php list item');
      }
    });

    logger.info({ page, count: items.length }, 'Parsed custom-php list page');
    return items;
  }

  async crawlDetail(ref: DetailRef, config: CustomPhpDepartmentConfig): Promise<NoticeDetail | null> {
    let url: string;
    if (ref.detailPath.startsWith('http')) {
      url = ref.detailPath;
    } else if (ref.detailPath.startsWith('?')) {
      url = `${config.baseUrl}${ref.detailPath}`;
    } else {
      // Fallback: construct URL from articleNo + boardParams
      const boardParamsStr = Object.entries(config.boardParams)
        .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
        .join('&');
      url = `${config.baseUrl}?page=view&idx=${ref.articleNo}&${boardParamsStr}`;
    }

    try {
      logger.debug({ url, articleNo: ref.articleNo }, 'Fetching custom-php detail page');
      const html = await this.fetcher.fetch(url);
      const $ = loadHtml(html);

      // Content
      const $content = $(config.selectors.detailContent);
      const content = $content.html()?.trim() || '';
      const contentText = $content.text().trim();

      // No separate attachment section found in cal.skku.edu
      const attachments: { name: string; url: string }[] = [];

      return { content, contentText, attachments };
    } catch (err) {
      logger.error({ articleNo: ref.articleNo, error: (err as Error).message }, 'Failed to fetch custom-php detail');
      return null;
    }
  }
}
