import * as cheerio from 'cheerio';
import type { AnyNode } from 'domhandler';

export type CheerioAPI = cheerio.CheerioAPI;

export function loadHtml(html: string): CheerioAPI {
  return cheerio.load(html);
}

export function extractText($el: cheerio.Cheerio<AnyNode>): string {
  return $el.text().trim();
}

export function extractAttr(
  $el: cheerio.Cheerio<AnyNode>,
  attr: string
): string | undefined {
  return $el.attr(attr)?.trim();
}
