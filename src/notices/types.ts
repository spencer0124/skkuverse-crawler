import type { NoticeListItem, NoticeDetail } from './normalizer.js';

// ── Pagination ──────────────────────────────────────────

export interface OffsetPaginationConfig {
  type: 'offset';
  param: string;
  limit: number;
}

export interface PageNumPaginationConfig {
  type: 'pageNum';
  param: string;
  limit: number;
}

export type PaginationConfig = OffsetPaginationConfig | PageNumPaginationConfig;

// ── Department Config ───────────────────────────────────

export interface BaseDepartmentConfig {
  id: string;
  name: string;
  strategy: string;
  baseUrl: string;
  pagination: PaginationConfig;
  extraParams?: Record<string, string>;
}

export interface SkkuStandardDepartmentConfig extends BaseDepartmentConfig {
  strategy: 'skku-standard';
  selectors: {
    listItem: string;
    category: string;
    titleLink: string;
    infoList: string;
    detailContent: string;
    attachmentList: string;
  };
  infoParser?: 'standard' | 'labeled';
  attachmentParser?: 'href' | 'onclick';
  pagination: OffsetPaginationConfig;
}

export interface WordPressApiDepartmentConfig extends BaseDepartmentConfig {
  strategy: 'wordpress-api';
  categoryId?: number;
  pagination: PageNumPaginationConfig;
}

export interface SkkumedAspDepartmentConfig extends BaseDepartmentConfig {
  strategy: 'skkumed-asp';
  encoding: string;             // 'euc-kr'
  detailBaseUrl: string;        // 'https://www.skkumed.ac.kr/community_notice_w.asp'
  selectors: {
    listItem: string;
    titleLink: string;
    infoList: string;
    detailContent: string;
    attachmentList: string;
  };
  pagination: PageNumPaginationConfig;
}

export interface JspDormDepartmentConfig extends BaseDepartmentConfig {
  strategy: 'jsp-dorm';
  boardNo: string;
  selectors: {
    listRow: string;          // "table.list_table tbody tr"
    pinnedRow: string;        // "table.list_table tbody tr[style*=\"background:#f4f4f4\"]"
    titleLink: string;        // "td.title a"
    detailContent: string;    // "div#article_text"
    attachmentLink: string;   // "table.view_table a[href*=\"download.jsp\"]"
  };
  pagination: OffsetPaginationConfig;
}

export interface CustomPhpDepartmentConfig extends BaseDepartmentConfig {
  strategy: 'custom-php';
  boardParams: Record<string, string>;  // { hCode: "BOARD", bo_idx: "17" }
  articleIdParam: string;               // "idx"
  selectors: {
    listRow: string;
    titleLink: string;
    category: string;
    views: string;
    date: string;
    detailContent: string;
  };
  pagination: PageNumPaginationConfig;
}

export interface GnuboardDepartmentConfig extends BaseDepartmentConfig {
  strategy: 'gnuboard';
  boardParam: string;      // "bo_table"
  boardName: string;       // "N4", "notice"
  articleIdParam: string;  // "wr_id"
  skinType: 'table' | 'list';  // bio=table, pharm=list
  selectors: {
    listRow: string;        // table: "#bo_list .spage table.table tbody tr" / list: "ol.bo_lst > li"
    titleLink: string;      // table: "td:nth-child(2) a" / list: "li > a"
    titleText?: string;     // list only: "article.bo_info h2"
    author: string;         // table: "td:nth-child(3) .sv_member" / list: "span.write"
    views?: string;         // table: "td:nth-child(4)" / list: absent
    date: string;           // table: "td:nth-child(5)" / list: "span.time"
    detailContent: string;  // "#bo_v_con"
    detailAttachment: string; // table: "#bo_v_file ul li a.view_file_download" / list: "div.bo_file_layer ul li a"
  };
  pagination: PageNumPaginationConfig;
}

export interface GnuboardCustomDepartmentConfig extends BaseDepartmentConfig {
  strategy: 'gnuboard-custom';
  boardParam: string;       // "tbl"
  boardName: string;        // "bbs42"
  articleIdParam: string;   // "num"
  detailMode: string;       // "VIEW"
  selectors: {
    listRow: string;
    titleLink: string;
    date: string;
    meta: string;
    detailContent: string;
    detailAttachment: string;
  };
  pagination: PageNumPaginationConfig;
}

/** Union of all supported department config types */
export type DepartmentConfig =
  | SkkuStandardDepartmentConfig
  | WordPressApiDepartmentConfig
  | SkkumedAspDepartmentConfig
  | JspDormDepartmentConfig
  | CustomPhpDepartmentConfig
  | GnuboardDepartmentConfig
  | GnuboardCustomDepartmentConfig;

// ── Strategy ────────────────────────────────────────────

export interface DetailRef {
  articleNo: number;
  detailPath: string;
}

export interface CrawlStrategy {
  crawlList(config: DepartmentConfig, page: number): Promise<NoticeListItem[]>;
  crawlDetail(ref: DetailRef, config: DepartmentConfig): Promise<NoticeDetail | null>;
}
