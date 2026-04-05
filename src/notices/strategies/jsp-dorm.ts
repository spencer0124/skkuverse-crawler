import { Fetcher } from '../../shared/fetcher.js';
import { loadHtml } from '../parser.js';
import { NoticeListItem, NoticeDetail } from '../normalizer.js';
import type { JspDormDepartmentConfig, CrawlStrategy, DetailRef } from '../types.js';
import logger from '../../shared/logger.js';

export class JspDormStrategy implements CrawlStrategy {
  private fetcher: Fetcher;

  constructor(fetcher: Fetcher) {
    this.fetcher = fetcher;
  }

  async crawlList(config: JspDormDepartmentConfig, page: number): Promise<NoticeListItem[]> {
    const offset = page * config.pagination.limit;
    const url = `${config.baseUrl}?mode=list&board_no=${config.boardNo}&${config.pagination.param}=${offset}`;

    logger.info({ url, page }, 'Fetching JSP dorm list page');
    const html = await this.fetcher.fetch(url);
    const $ = loadHtml(html);

    const items: NoticeListItem[] = [];
    const pinnedSelector = config.selectors.pinnedRow;

    $(config.selectors.listRow).each((_i, el) => {
      try {
        const $tr = $(el);

        // Skip pinned notices (they repeat on every page)
        // Only collect pinned notices on page 0
        const isPinned = $tr.is(pinnedSelector);
        if (isPinned && page > 0) return;

        const $tds = $tr.find('td');
        if ($tds.length < 6) return; // skip malformed rows

        // td indices: 0=No, 1=Category, 2=Title, 3=File, 4=Date, 5=Views
        const category = $tds.eq(1).text().trim();
        const $titleLink = $tds.eq(2).find('a');
        const title = $titleLink.text().trim();
        const href = $titleLink.attr('href') || '';
        const date = $tds.eq(4).text().trim();
        const views = parseInt($tds.eq(5).text().trim(), 10) || 0;

        // Extract article_no (snake_case!)
        const match = href.match(/article_no=(\d+)/);
        if (!match) {
          logger.warn({ href, title }, 'Could not extract article_no from JSP href');
          return;
        }

        items.push({
          articleNo: parseInt(match[1], 10),
          title,
          category,
          author: '',  // No author info in JSP dorm boards
          date,
          views,
          detailPath: href,
        });
      } catch (err) {
        logger.warn({ error: (err as Error).message }, 'Failed to parse JSP dorm list item');
      }
    });

    logger.info({ page, count: items.length }, 'Parsed JSP dorm list page');
    return items;
  }

  async crawlDetail(ref: DetailRef, config: JspDormDepartmentConfig): Promise<NoticeDetail | null> {
    let url: string;
    if (ref.detailPath.startsWith('http')) {
      url = ref.detailPath;
    } else if (ref.detailPath.startsWith('?')) {
      url = `${config.baseUrl}${ref.detailPath}`;
    } else {
      url = `${config.baseUrl}?mode=view&article_no=${ref.articleNo}&board_no=${config.boardNo}`;
    }

    try {
      logger.debug({ url, articleNo: ref.articleNo }, 'Fetching JSP dorm detail page');
      const html = await this.fetcher.fetch(url);
      const $ = loadHtml(html);

      // Content: div#article_text
      const $content = $(config.selectors.detailContent);
      const content = $content.html()?.trim() || '';
      const contentText = $content.text().trim();

      // Attachments: table.view_table a[href*="download.jsp"]
      const attachments: { name: string; url: string }[] = [];
      $(config.selectors.attachmentLink).each((_i, el) => {
        const $a = $(el);
        // Get text content excluding img alt text
        const name = $a.clone().children('img').remove().end().text().trim();
        const fileHref = $a.attr('href') || '';
        if (name && fileHref) {
          const origin = new URL(config.baseUrl).origin;
          const fullUrl = fileHref.startsWith('http') ? fileHref
            : `${origin}${fileHref.startsWith('/') ? '' : '/'}${fileHref}`;
          attachments.push({ name, url: fullUrl });
        }
      });

      return { content, contentText, attachments };
    } catch (err) {
      logger.error({ articleNo: ref.articleNo, error: (err as Error).message }, 'Failed to fetch JSP dorm detail');
      return null;
    }
  }
}
