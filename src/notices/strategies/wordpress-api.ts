import { Fetcher } from '../../shared/fetcher.js';
import { loadHtml } from '../parser.js';
import { NoticeListItem, NoticeDetail } from '../normalizer.js';
import type { WordPressApiDepartmentConfig, CrawlStrategy, DetailRef } from '../types.js';
import logger from '../../shared/logger.js';

/** Decode WP HTML entities (e.g. `&#8211;`, `&amp;`) using cheerio instead of adding a dep */
function decodeHtmlEntities(text: string): string {
  const $ = loadHtml(`<span>${text}</span>`);
  return $('span').text();
}

export class WordPressApiStrategy implements CrawlStrategy {
  private fetcher: Fetcher;
  private detailCache = new Map<number, NoticeDetail>();

  constructor(fetcher: Fetcher) {
    this.fetcher = fetcher;
  }

  async crawlList(config: WordPressApiDepartmentConfig, page: number): Promise<NoticeListItem[]> {
    // WP REST API uses 1-based pages, our orchestrator uses 0-based
    const wpPage = page + 1;

    const params = new URLSearchParams({
      rest_route: '/wp/v2/posts',
      per_page: String(config.pagination.limit),
      page: String(wpPage),
      _fields: 'id,title,date,link,content,categories',
    });
    if (config.categoryId) {
      params.set('categories', String(config.categoryId));
    }

    const url = `${config.baseUrl}/?${params}`;
    logger.info({ url, page }, 'Fetching WP REST API');

    let data: any[];
    try {
      const response = await this.fetcher.fetch(url);
      data = JSON.parse(response);
    } catch (err) {
      // WP returns 400 when page exceeds total pages — treat as empty
      if ((err as any)?.response?.status === 400) return [];
      throw err;
    }

    if (!Array.isArray(data) || data.length === 0) return [];

    const items: NoticeListItem[] = [];

    for (const post of data) {
      const articleNo = post.id;
      const title = decodeHtmlEntities(post.title?.rendered || '');
      const date = (post.date || '').split('T')[0]; // "2026-03-25T14:55:24" → "2026-03-25"
      const detailPath = post.link || '';

      items.push({
        articleNo,
        title,
        category: '',
        author: '',
        date,
        views: 0,
        detailPath,
      });

      // Cache detail content from list response to avoid N extra HTTP requests
      if (post.content?.rendered) {
        const contentHtml = post.content.rendered;
        const $ = loadHtml(contentHtml);
        const contentText = $.text().trim();
        const attachments = this.extractAttachments($, config.baseUrl);
        this.detailCache.set(articleNo, { content: contentHtml, contentText, attachments });
      }
    }

    return items;
  }

  async crawlDetail(ref: DetailRef, config: WordPressApiDepartmentConfig): Promise<NoticeDetail | null> {
    // Check cache first (populated by crawlList)
    const cached = this.detailCache.get(ref.articleNo);
    if (cached) {
      this.detailCache.delete(ref.articleNo); // free memory
      return cached;
    }

    // Cache miss — fetch individual post
    try {
      const url = `${config.baseUrl}/?rest_route=/wp/v2/posts/${ref.articleNo}&_fields=content`;
      logger.debug({ url, articleNo: ref.articleNo }, 'Fetching WP post detail');
      const response = await this.fetcher.fetch(url);
      const post = JSON.parse(response);
      const contentHtml = post.content?.rendered || '';
      const $ = loadHtml(contentHtml);
      return {
        content: contentHtml,
        contentText: $.text().trim(),
        attachments: this.extractAttachments($, config.baseUrl),
      };
    } catch (err) {
      logger.error({ articleNo: ref.articleNo, error: (err as Error).message }, 'Failed to fetch WP post');
      return null;
    }
  }

  private extractAttachments($: ReturnType<typeof loadHtml>, baseUrl: string): { name: string; url: string }[] {
    const fileExtensions = /\.(pdf|hwp|hwpx|xlsx|xls|docx|doc|pptx|ppt|zip|rar|7z)$/i;
    const attachments: { name: string; url: string }[] = [];

    $('a[href]').each((_i, el) => {
      const href = $(el).attr('href') ?? '';
      if (fileExtensions.test(href)) {
        const name = $(el).text().trim() || href.split('/').pop() || 'unknown';
        const fullUrl = href.startsWith('http') ? href : new URL(href, baseUrl).href;
        attachments.push({ name, url: fullUrl });
      }
    });

    return attachments;
  }
}
