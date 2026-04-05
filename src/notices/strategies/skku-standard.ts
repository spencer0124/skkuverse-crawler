import { Fetcher } from '../../shared/fetcher.js';
import { loadHtml, extractText, extractAttr } from '../parser.js';
import { NoticeListItem, NoticeDetail } from '../normalizer.js';
import type { SkkuStandardDepartmentConfig, CrawlStrategy, DetailRef } from '../types.js';
import logger from '../../shared/logger.js';

export class SkkuStandardStrategy implements CrawlStrategy {
  private fetcher: Fetcher;

  constructor(fetcher: Fetcher) {
    this.fetcher = fetcher;
  }

  async crawlList(config: SkkuStandardDepartmentConfig, page: number): Promise<NoticeListItem[]> {
    const offset = page * config.pagination.limit;
    const extra = config.extraParams
      ? Object.entries(config.extraParams).map(([k, v]) => `${k}=${v}`).join('&') + '&'
      : '';
    const url = `${config.baseUrl}?${extra}mode=list&articleLimit=${config.pagination.limit}&${config.pagination.param}=${offset}`;

    logger.info({ url, page }, 'Fetching list page');
    const html = await this.fetcher.fetch(url);
    const $ = loadHtml(html);

    const items: NoticeListItem[] = [];

    $(config.selectors.listItem).each((_i, el) => {
      try {
        const $el = $(el);

        // Category: [행사/세미나] etc.
        const categoryRaw = extractText($el.find(config.selectors.category));
        const category = categoryRaw.replace(/^\[|\]$/g, '');

        // Title + article link
        const $titleLink = $el.find(config.selectors.titleLink);
        const titleRaw = extractText($titleLink);
        const title = titleRaw.trim();
        const href = extractAttr($titleLink, 'href') || '';

        // Extract articleNo from href: ?mode=view&articleNo=135890&...
        // Type H (portal boardId) uses itemId instead of articleNo
        const articleNoMatch = href.match(/articleNo=(\d+)/) || href.match(/itemId=(\d+)/);
        if (!articleNoMatch) {
          logger.warn({ href, title }, 'Could not extract articleNo from href');
          return; // skip this item
        }
        const articleNo = parseInt(articleNoMatch[1], 10);

        // Info list: [No.24662, 작성자, 날짜, 조회수N]
        const $infoItems = $el.find(config.selectors.infoList);
        const infoTexts: string[] = [];
        $infoItems.each((_j, li) => {
          infoTexts.push($(li).text().trim());
        });

        // Parse info fields
        let author: string;
        let date: string;
        let views: number;

        if (config.infoParser === 'labeled') {
          // Label-based meta: "POSTED DATE : 2026-03-20", "WRITER : 화학과", "HIT : 280"
          const infoMap: Record<string, string> = {};
          for (const text of infoTexts) {
            const match = text.match(/^(.+?)\s*:\s*(.+)$/);
            if (match) {
              infoMap[match[1].trim().toUpperCase()] = match[2].trim();
            }
          }
          date = infoMap['POSTED DATE'] || '';
          author = infoMap['WRITER'] || '';
          const hitsText = infoMap['HIT'] || '0';
          const hitsMatch = hitsText.match(/(\d+)/);
          views = hitsMatch ? parseInt(hitsMatch[1], 10) : 0;
        } else {
          // Standard: infoTexts[0]: "No.24662" → extract number part (optional, not used as articleNo)
          author = infoTexts[1] || '';
          date = infoTexts[2] || '';
          const viewsText = infoTexts[3] || '0';
          const viewsMatch = viewsText.match(/(\d+)/);
          views = viewsMatch ? parseInt(viewsMatch[1], 10) : 0;
        }

        items.push({
          articleNo,
          title,
          category,
          author,
          date,
          views,
          detailPath: href,
        });
      } catch (err) {
        logger.warn({ error: (err as Error).message }, 'Failed to parse list item');
      }
    });

    logger.info({ page, count: items.length }, 'Parsed list page');
    return items;
  }

  async crawlDetail(ref: DetailRef, config: SkkuStandardDepartmentConfig): Promise<NoticeDetail | null> {
    // Use detailPath from list page when available (handles itemId/viewBoardId patterns)
    let url: string;
    if (ref.detailPath.startsWith('http')) {
      url = ref.detailPath;
    } else if (ref.detailPath.startsWith('?')) {
      // Inject extraParams (e.g., boardId) if not already present in detailPath
      if (config.extraParams) {
        const params = new URLSearchParams(ref.detailPath.slice(1));
        for (const [k, v] of Object.entries(config.extraParams)) {
          if (!params.has(k)) params.set(k, v);
        }
        url = `${config.baseUrl}?${params.toString()}`;
      } else {
        url = `${config.baseUrl}${ref.detailPath}`;
      }
    } else {
      // Fallback: construct standard SKKU URL
      const extra = config.extraParams
        ? Object.entries(config.extraParams).map(([k, v]) => `${k}=${v}`).join('&') + '&'
        : '';
      url = `${config.baseUrl}?${extra}mode=view&articleNo=${ref.articleNo}&article.offset=0&articleLimit=10`;
    }

    try {
      logger.debug({ url, articleNo: ref.articleNo }, 'Fetching detail page');
      const html = await this.fetcher.fetch(url);
      const $ = loadHtml(html);

      // Content: try configured selector first, then fallback for newer templates
      let $content = $(config.selectors.detailContent);
      if ($content.length === 0) {
        // Department sites (cse, mech, etc.) use div.board-view-content-wrap
        // instead of dl.board-write-box dd used by www.skku.edu
        const fallbacks = ['div.board-view-content-wrap', 'div.fr-view'];
        for (const sel of fallbacks) {
          $content = $(sel);
          if ($content.length > 0) {
            logger.info({ articleNo: ref.articleNo, fallback: sel }, 'Used fallback content selector');
            break;
          }
        }
      }
      const content = $content.html()?.trim() || '';
      const contentText = $content.text().trim();

      // Attachments
      const attachments: { name: string; url: string }[] = [];
      $(config.selectors.attachmentList).each((_i, el) => {
        const $a = $(el);
        const name = extractText($a);

        let fileUrl: string | undefined;
        if (config.attachmentParser === 'onclick') {
          // Parse <button onclick="location.href='...'">
          const onclick = extractAttr($a, 'onclick') || '';
          const onclickMatch = onclick.match(/location\.href='([^']+)'/);
          fileUrl = onclickMatch ? onclickMatch[1].replace(/&amp;/g, '&') : undefined;
        } else {
          fileUrl = extractAttr($a, 'href');
        }

        if (name && fileUrl && fileUrl !== '#') {
          let fullUrl: string;
          if (fileUrl.startsWith('http')) {
            fullUrl = fileUrl;
          } else if (fileUrl.startsWith('?')) {
            fullUrl = `${config.baseUrl}${fileUrl}`;
          } else {
            // Relative path → use origin from baseUrl
            const origin = new URL(config.baseUrl).origin;
            fullUrl = `${origin}${fileUrl.startsWith('/') ? '' : '/'}${fileUrl}`;
          }
          attachments.push({ name, url: fullUrl });
        }
      });

      return { content, contentText, attachments };
    } catch (err) {
      logger.error({ articleNo: ref.articleNo, error: (err as Error).message }, 'Failed to fetch detail page');
      return null;
    }
  }
}
