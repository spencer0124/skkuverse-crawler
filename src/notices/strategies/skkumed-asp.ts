import iconv from 'iconv-lite';
import { Fetcher } from '../../shared/fetcher.js';
import { loadHtml, extractText, extractAttr } from '../parser.js';
import { NoticeListItem, NoticeDetail } from '../normalizer.js';
import type { SkkumedAspDepartmentConfig, CrawlStrategy, DetailRef } from '../types.js';
import logger from '../../shared/logger.js';

export class SkkumedAspStrategy implements CrawlStrategy {
  private fetcher: Fetcher;

  constructor(fetcher: Fetcher) {
    this.fetcher = fetcher;
  }

  private async fetchEucKr(url: string): Promise<string> {
    const buf = await this.fetcher.fetchBinary(url);
    return iconv.decode(buf, 'euc-kr');
  }

  async crawlList(config: SkkumedAspDepartmentConfig, page: number): Promise<NoticeListItem[]> {
    // Our orchestrator uses 0-based pages, ASP uses 1-based pg parameter
    const pgNum = page + 1;

    const extra = config.extraParams
      ? Object.entries(config.extraParams).map(([k, v]) => `${k}=${v}`).join('&') + '&'
      : '';
    const url = `${config.baseUrl}?${extra}${config.pagination.param}=${pgNum}`;

    logger.info({ url, page }, 'Fetching ASP list page');
    const html = await this.fetchEucKr(url);
    const $ = loadHtml(html);

    const items: NoticeListItem[] = [];

    $(config.selectors.listItem).each((_i, el) => {
      try {
        const $el = $(el);

        // Title + link
        const $titleLink = $el.find(config.selectors.titleLink);
        const title = extractText($titleLink).replace(/^·\s*/, '').trim();
        const href = extractAttr($titleLink, 'href') || '';

        // Extract articleNo: number=(\d+)
        const articleNoMatch = href.match(/number=(\d+)/);
        if (!articleNoMatch) {
          logger.warn({ href, title }, 'Could not extract articleNo from ASP href');
          return;
        }
        const articleNo = parseInt(articleNoMatch[1], 10);

        // Info list: [No.N, author, date, views]
        const $infoItems = $el.find(config.selectors.infoList);
        const infoTexts: string[] = [];
        $infoItems.each((_j, li) => {
          infoTexts.push($(li).text().trim());
        });

        const author = infoTexts[1] || '';
        const date = infoTexts[2] || '';
        const viewsText = infoTexts[3] || '0';
        const viewsMatch = viewsText.match(/(\d+)/);
        const views = viewsMatch ? parseInt(viewsMatch[1], 10) : 0;

        items.push({
          articleNo,
          title,
          category: '',  // ASP site has no category
          author,
          date,
          views,
          detailPath: href,
        });
      } catch (err) {
        logger.warn({ error: (err as Error).message }, 'Failed to parse ASP list item');
      }
    });

    logger.info({ page, count: items.length }, 'Parsed ASP list page');
    return items;
  }

  async crawlDetail(ref: DetailRef, config: SkkumedAspDepartmentConfig): Promise<NoticeDetail | null> {
    // Build detail URL
    let url: string;
    if (ref.detailPath.startsWith('http')) {
      url = ref.detailPath;
    } else {
      // Relative path like "community_notice_w.asp?bcode=nt&number=4665&pg=1"
      const origin = new URL(config.baseUrl).origin;
      url = `${origin}/${ref.detailPath.replace(/^\//, '')}`;
    }

    try {
      logger.debug({ url, articleNo: ref.articleNo }, 'Fetching ASP detail page');
      const html = await this.fetchEucKr(url);
      const $ = loadHtml(html);

      // Content: div.board-view-content-wrap div.fr-view
      const $content = $(config.selectors.detailContent);
      // Clean up DEXT5 editor artifacts
      $content.find('style').remove();
      $content.find('head').remove();
      const content = $content.html()?.trim() || '';
      const contentText = $content.text().trim();

      // Attachments: ul.board-view-file-wrap li a
      const attachments: { name: string; url: string }[] = [];
      $(config.selectors.attachmentList).each((_i, el) => {
        const $a = $(el);
        const name = extractText($a);
        const fileUrl = extractAttr($a, 'href');
        if (name && fileUrl && fileUrl !== '#') {
          let fullUrl: string;
          if (fileUrl.startsWith('http')) {
            fullUrl = fileUrl;
          } else {
            const origin = new URL(config.baseUrl).origin;
            fullUrl = `${origin}/${fileUrl.replace(/^\//, '')}`;
          }
          attachments.push({ name, url: fullUrl });
        }
      });

      return { content, contentText, attachments };
    } catch (err) {
      logger.error({ articleNo: ref.articleNo, error: (err as Error).message }, 'Failed to fetch ASP detail');
      return null;
    }
  }
}
