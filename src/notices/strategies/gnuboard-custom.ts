import { Fetcher } from '../../shared/fetcher.js';
import { loadHtml } from '../parser.js';
import { NoticeListItem, NoticeDetail } from '../normalizer.js';
import type { GnuboardCustomDepartmentConfig, CrawlStrategy, DetailRef } from '../types.js';
import logger from '../../shared/logger.js';

/**
 * Clean HWP editor artifacts from HTML content.
 * Removes <!--[data-hwpjson]...[data-hwpjson]--> comments and data-hwpjson attributes.
 */
function cleanHwpArtifacts(html: string): string {
  // Remove HWP JSON comments: <!--[data-hwpjson]...[data-hwpjson]-->
  let cleaned = html.replace(/<!--\[data-hwpjson\][\s\S]*?\[data-hwpjson\]-->/g, '');
  // Remove data-hwpjson attributes from tags
  cleaned = cleaned.replace(/\s*data-hwpjson="[^"]*"/g, '');
  return cleaned;
}

export class GnuboardCustomStrategy implements CrawlStrategy {
  private fetcher: Fetcher;

  constructor(fetcher: Fetcher) {
    this.fetcher = fetcher;
  }

  async crawlList(config: GnuboardCustomDepartmentConfig, page: number): Promise<NoticeListItem[]> {
    const pageNum = page + 1; // 0-based → 1-based
    const url = `${config.baseUrl}?${config.boardParam}=${config.boardName}&page=${pageNum}`;

    logger.info({ url, page }, 'Fetching gnuboard-custom list page');
    const html = await this.fetcher.fetch(url);
    const $ = loadHtml(html);

    const items: NoticeListItem[] = [];

    $(config.selectors.listRow).each((_i, el) => {
      try {
        const $tr = $(el);
        const $tds = $tr.find('td');
        if ($tds.length < 2) return; // skip header rows

        // Skip notice rows (pinned) on page > 0 to avoid duplicates
        if (page > 0 && $tr.find('img[src*="btn_notice"]').length > 0) return;

        // Title from configured selector
        const $titleLink = $tr.find(config.selectors.titleLink);
        const title = $titleLink.text().trim();
        if (!title) return;

        const href = $titleLink.attr('href') || '';

        // Extract articleNo via num=(\d+)
        const articleNoMatch = href.match(/num=(\d+)/);
        if (!articleNoMatch) {
          logger.warn({ href, title }, 'Could not extract num from gnuboard-custom href');
          return;
        }
        const articleNo = parseInt(articleNoMatch[1], 10);

        // Date from configured selector
        const date = $tr.find(config.selectors.date).text().trim();

        // Meta from configured selector — "관리자 | 2026-03-09 | 조회수 : 147"
        const metaText = $tr.find(config.selectors.meta).text().trim();
        const parts = metaText.split('|').map((s) => s.trim());
        const author = parts[0] || '';
        const viewsMatch = metaText.match(/조회수\s*:\s*(\d+)/);
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
        logger.warn({ error: (err as Error).message }, 'Failed to parse gnuboard-custom list item');
      }
    });

    logger.info({ page, count: items.length }, 'Parsed gnuboard-custom list page');
    return items;
  }

  async crawlDetail(ref: DetailRef, config: GnuboardCustomDepartmentConfig): Promise<NoticeDetail | null> {
    let url: string;
    if (ref.detailPath.startsWith('http')) {
      url = ref.detailPath;
    } else if (ref.detailPath.startsWith('?')) {
      url = `${config.baseUrl}${ref.detailPath}`;
    } else {
      url = `${config.baseUrl}?${config.boardParam}=${config.boardName}&mode=${config.detailMode}&num=${ref.articleNo}`;
    }

    try {
      logger.debug({ url, articleNo: ref.articleNo }, 'Fetching gnuboard-custom detail page');
      const html = await this.fetcher.fetch(url);
      const $ = loadHtml(html);

      // Content — clean HWP editor artifacts
      const $content = $(config.selectors.detailContent);
      const rawHtml = $content.html()?.trim() || '';
      const content = cleanHwpArtifacts(rawHtml);
      // Re-parse cleaned content for text extraction
      const $cleaned = loadHtml(content);
      const contentText = $cleaned.text().trim();

      // Attachments: a[href*="download.php"]
      const attachments: { name: string; url: string }[] = [];
      const origin = new URL(config.baseUrl).origin;

      $(config.selectors.detailAttachment).each((_i, el) => {
        const $a = $(el);
        const name = $a.text().trim();
        let fileHref = $a.attr('href') || '';

        if (!name || !fileHref) return;

        // Resolve relative download URLs
        if (fileHref.startsWith('/')) {
          fileHref = `${origin}${fileHref}`;
        } else if (!fileHref.startsWith('http')) {
          fileHref = `${origin}/${fileHref}`;
        }

        attachments.push({ name, url: fileHref });
      });

      return { content, contentText, attachments };
    } catch (err) {
      logger.error({ articleNo: ref.articleNo, error: (err as Error).message }, 'Failed to fetch gnuboard-custom detail');
      return null;
    }
  }
}
