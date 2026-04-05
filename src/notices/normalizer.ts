import { cleanHtml as generateCleanHtml } from './cleanHtml.js';

export interface Notice {
  articleNo: number;
  title: string;
  category: string;
  author: string;
  department: string;
  date: string; // YYYY-MM-DD
  lastModified?: string;
  views: number;
  content: string | null; // detail HTML (null if fetch failed)
  contentText: string | null; // plain text via cheerio .text()
  cleanHtml: string | null; // sanitized HTML for mobile rendering
  attachments: { name: string; url: string }[];
  sourceUrl: string;
  detailPath: string; // original href from list page (for re-crawl)
  sourceDeptId: string;
  crawledAt: Date;
}

export interface NoticeListItem {
  articleNo: number;
  title: string;
  category: string;
  author: string;
  date: string;
  views: number;
  detailPath: string; // relative or absolute URL to detail page
}

export interface NoticeDetail {
  content: string;
  contentText: string;
  attachments: { name: string; url: string }[];
}

export function buildNotice(
  listItem: NoticeListItem,
  detail: NoticeDetail | null,
  config: { department: string; sourceDeptId: string; baseUrl: string }
): Notice {
  // Build sourceUrl from detailPath: use as-is if absolute, otherwise combine with baseUrl
  let sourceUrl: string;
  if (listItem.detailPath.startsWith('http')) {
    sourceUrl = listItem.detailPath;
  } else if (listItem.detailPath.startsWith('?')) {
    sourceUrl = `${config.baseUrl}${listItem.detailPath}`;
  } else {
    // Fallback: construct from baseUrl + articleNo (SKKU standard pattern)
    sourceUrl = `${config.baseUrl}?mode=view&articleNo=${listItem.articleNo}`;
  }

  return {
    articleNo: listItem.articleNo,
    title: listItem.title,
    category: listItem.category,
    author: listItem.author,
    department: config.department,
    date: listItem.date,
    views: listItem.views,
    content: detail?.content ?? null,
    contentText: detail?.contentText ?? null,
    cleanHtml: detail?.content ? generateCleanHtml(detail.content, config.baseUrl) : null,
    attachments: detail?.attachments ?? [],
    sourceUrl,
    detailPath: listItem.detailPath,
    sourceDeptId: config.sourceDeptId,
    crawledAt: new Date(),
  };
}
