import { Fetcher } from '../../shared/fetcher.js';
import { loadHtml } from '../parser.js';
import { NoticeListItem, NoticeDetail } from '../normalizer.js';
import type { GnuboardDepartmentConfig, CrawlStrategy, DetailRef } from '../types.js';
import logger from '../../shared/logger.js';

/**
 * Normalize date strings from Gnuboard boards.
 * - "MM-DD" (no year) → prepend current year; if month is in the future, use previous year
 * - "YY-MM-DD" → prepend "20"
 * - Otherwise return as-is
 */
function normalizeDate(dateStr: string): string {
  if (/^\d{2}-\d{2}$/.test(dateStr)) {
    const now = new Date();
    const year = now.getFullYear();
    const month = parseInt(dateStr.split('-')[0], 10);
    const adjustedYear = month > now.getMonth() + 1 ? year - 1 : year;
    return `${adjustedYear}-${dateStr}`;
  }
  if (/^\d{2}-\d{2}-\d{2}$/.test(dateStr)) {
    return `20${dateStr}`;
  }
  return dateStr;
}

export class GnuboardStrategy implements CrawlStrategy {
  private fetcher: Fetcher;

  constructor(fetcher: Fetcher) {
    this.fetcher = fetcher;
  }

  async crawlList(config: GnuboardDepartmentConfig, page: number): Promise<NoticeListItem[]> {
    const pageNum = page + 1; // 0-based → 1-based
    const url = `${config.baseUrl}?${config.boardParam}=${config.boardName}&page=${pageNum}`;

    logger.info({ url, page }, 'Fetching gnuboard list page');
    const html = await this.fetcher.fetch(url);
    const $ = loadHtml(html);

    const items: NoticeListItem[] = [];

    if (config.skinType === 'table') {
      this.parseTableSkin($, config, items);
    } else {
      this.parseListSkin($, config, items);
    }

    logger.info({ page, count: items.length }, 'Parsed gnuboard list page');
    return items;
  }

  private parseTableSkin(
    $: ReturnType<typeof loadHtml>,
    config: GnuboardDepartmentConfig,
    items: NoticeListItem[]
  ): void {
    $(config.selectors.listRow).each((_i, el) => {
      try {
        const $tr = $(el);
        const $tds = $tr.find('td');
        if ($tds.length < 2) return; // skip malformed rows

        // Title + link
        const $titleLink = $tr.find(config.selectors.titleLink);
        const title = $titleLink.text().trim();
        if (!title) return;

        let href = $titleLink.attr('href') || '';

        // Extract articleNo via wr_id=(\d+)
        const articleNoMatch = href.match(/wr_id=(\d+)/);
        if (!articleNoMatch) {
          logger.warn({ href, title }, 'Could not extract wr_id from gnuboard href');
          return;
        }
        const articleNo = parseInt(articleNoMatch[1], 10);

        // Author
        const author = $tr.find(config.selectors.author).text().trim();

        // Views
        const viewsText = config.selectors.views ? $tr.find(config.selectors.views).text().trim() : '0';
        const viewsMatch = viewsText.match(/(\d+)/);
        const views = viewsMatch ? parseInt(viewsMatch[1], 10) : 0;

        // Date — bio uses MM-DD format
        const dateRaw = $tr.find(config.selectors.date).text().trim();
        const date = normalizeDate(dateRaw);

        items.push({
          articleNo,
          title,
          category: '',
          author,
          date,
          views,
          detailPath: href,
        });
      } catch (err) {
        logger.warn({ error: (err as Error).message }, 'Failed to parse gnuboard table list item');
      }
    });
  }

  private parseListSkin(
    $: ReturnType<typeof loadHtml>,
    config: GnuboardDepartmentConfig,
    items: NoticeListItem[]
  ): void {
    $(config.selectors.listRow).each((_i, el) => {
      try {
        const $el = $(el);

        // The <a> wraps the entire <li>
        const $link = $el.find(config.selectors.titleLink);
        let href = $link.attr('href') || '';

        // Fix protocol-relative URLs (e.g. //pharm.skku.edu/...)
        if (href.startsWith('//')) {
          href = 'https:' + href;
        }

        // Extract articleNo via wr_id=(\d+)
        const articleNoMatch = href.match(/wr_id=(\d+)/);
        if (!articleNoMatch) {
          logger.warn({ href }, 'Could not extract wr_id from gnuboard list skin href');
          return;
        }
        const articleNo = parseInt(articleNoMatch[1], 10);

        // Title — inside article.bo_info h2, excluding span.category
        let title = '';
        if (config.selectors.titleText) {
          const $h2 = $el.find(config.selectors.titleText);
          const categoryText = $h2.find('span.category').text().trim();
          const fullText = $h2.text().trim();
          title = fullText.replace(categoryText, '').trim();
        } else {
          title = $link.text().trim();
        }
        if (!title) return;

        // Author
        const author = $el.find(config.selectors.author).text().trim();

        // Date
        const dateRaw = $el.find(config.selectors.date).text().trim();
        const date = normalizeDate(dateRaw);

        // Views — not present in list skin typically
        const viewsText = config.selectors.views ? $el.find(config.selectors.views).text().trim() : '0';
        const viewsMatch = viewsText.match(/(\d+)/);
        const views = viewsMatch ? parseInt(viewsMatch[1], 10) : 0;

        items.push({
          articleNo,
          title,
          category: '',
          author,
          date,
          views,
          detailPath: href,
        });
      } catch (err) {
        logger.warn({ error: (err as Error).message }, 'Failed to parse gnuboard list skin item');
      }
    });
  }

  async crawlDetail(ref: DetailRef, config: GnuboardDepartmentConfig): Promise<NoticeDetail | null> {
    let url: string;
    if (ref.detailPath.startsWith('http')) {
      url = ref.detailPath;
    } else if (ref.detailPath.startsWith('?')) {
      url = `${config.baseUrl}${ref.detailPath}`;
    } else {
      url = `${config.baseUrl}?${config.boardParam}=${config.boardName}&wr_id=${ref.articleNo}`;
    }

    try {
      logger.debug({ url, articleNo: ref.articleNo }, 'Fetching gnuboard detail page');
      const html = await this.fetcher.fetch(url);
      const $ = loadHtml(html);

      // Content
      const $content = $(config.selectors.detailContent);
      const content = $content.html()?.trim() || '';
      const contentText = $content.text().trim();

      // Attachments
      const attachments: { name: string; url: string }[] = [];
      const origin = new URL(config.baseUrl).origin;

      $(config.selectors.detailAttachment).each((_i, el) => {
        const $a = $(el);
        const name = $a.text().trim();
        let fileHref = $a.attr('href') || '';

        if (!name || !fileHref) return;

        // Fix protocol-relative URLs
        if (fileHref.startsWith('//')) {
          fileHref = 'https:' + fileHref;
        }

        // Resolve relative download URLs (e.g. /bbs/download.php?...)
        if (fileHref.startsWith('/')) {
          fileHref = `${origin}${fileHref}`;
        } else if (!fileHref.startsWith('http')) {
          fileHref = `${origin}/${fileHref}`;
        }

        attachments.push({ name, url: fileHref });
      });

      return { content, contentText, attachments };
    } catch (err) {
      logger.error({ articleNo: ref.articleNo, error: (err as Error).message }, 'Failed to fetch gnuboard detail');
      return null;
    }
  }
}
