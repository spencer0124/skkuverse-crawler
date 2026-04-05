import * as cheerio from 'cheerio';
import type { AnyNode, Element } from 'domhandler';
import sanitize from 'sanitize-html';
import logger from '../shared/logger.js';

// ── Constants ──────────────────────────────────────────

/** Step 1: Selectors for junk elements to remove */
const REMOVE_SELECTORS = [
  'script', 'style', 'iframe', 'form', 'input', 'button',
  'tfoot',
  '.board-view-title-wrap',
  '.board-view-file-wrap',
  '.board-view-nav',
  'a[href*="mode=list"]',
];

/** Step 2: CSS properties to keep (everything else is stripped) */
const ALLOWED_STYLES = new Set([
  'color', 'background-color', 'text-align', 'text-decoration',
  'font-weight', 'font-style',
]);

/** Step 3: Only inline elements get font-weight→<strong> / font-style→<em> conversion */
const INLINE_ELEMENTS = new Set([
  'span', 'a', 'font', 'b', 'i', 'u', 'em', 'strong', 'mark',
]);

/** Step 5: sanitize-html configuration */
const SANITIZE_CONFIG: sanitize.IOptions = {
  allowedTags: [
    'p', 'br', 'div', 'span', 'h1', 'h2', 'h3', 'h4',
    'strong', 'b', 'em', 'i', 'u', 'mark',
    'ul', 'ol', 'li',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'img', 'a', 'hr',
  ],
  allowedAttributes: {
    'a': ['href'],
    'img': ['src', 'alt', 'width', 'height'],
    'td': ['colspan', 'rowspan'],
    'th': ['colspan', 'rowspan'],
    '*': ['style'],
  },
  allowedSchemesByTag: {
    img: ['http', 'https', 'data'],
  },
  allowedStyles: {
    '*': {
      'color': [/.*/],
      'background-color': [/.*/],
      'text-align': [/.*/],
      'text-decoration': [/.*/],
      'font-weight': [/.*/],
      'font-style': [/.*/],
    },
  },
};

/** Step 6: Elements to check for emptiness (excludes void elements) */
const REMOVABLE_EMPTY = 'p, span, div, strong, b, em, i, u, mark, h1, h2, h3, h4, a, li, td, th, tr, thead, tbody, table, ul, ol';

const MAX_EMPTY_PASSES = 10;

// ── Helpers ────────────────────────────────────────────

/** Filter inline style string, keeping only allowed CSS properties */
function filterStyles(styleStr: string): string {
  return styleStr
    .split(';')
    .map((decl) => decl.trim())
    .filter((decl) => {
      const colonIdx = decl.indexOf(':');
      if (colonIdx === -1) return false;
      const prop = decl.slice(0, colonIdx).trim().toLowerCase();
      return ALLOWED_STYLES.has(prop);
    })
    .join('; ');
}

/** Extract a specific CSS property value from a style string */
function getStyleProp(styleStr: string, prop: string): string | null {
  for (const decl of styleStr.split(';')) {
    const colonIdx = decl.indexOf(':');
    if (colonIdx === -1) continue;
    if (decl.slice(0, colonIdx).trim().toLowerCase() === prop) {
      return decl.slice(colonIdx + 1).trim();
    }
  }
  return null;
}

/** Remove a specific CSS property from a style string */
function removeStyleProp(styleStr: string, prop: string): string {
  return styleStr
    .split(';')
    .map((decl) => decl.trim())
    .filter((decl) => {
      const colonIdx = decl.indexOf(':');
      if (colonIdx === -1) return false;
      return decl.slice(0, colonIdx).trim().toLowerCase() !== prop;
    })
    .join('; ');
}

/** Resolve a relative URL against a base URL. Skips data:, mailto:, tel: schemes. */
function resolveUrl(relative: string, base: string): string {
  if (!relative || relative.startsWith('data:') || relative.startsWith('mailto:') || relative.startsWith('tel:')) {
    return relative;
  }
  try {
    return new URL(relative, base).href;
  } catch {
    return relative;
  }
}

/** Check if an element is effectively empty (no children, text is only whitespace/&nbsp;) */
function isEffectivelyEmpty($el: cheerio.Cheerio<AnyNode>): boolean {
  if ($el.children().length > 0) return false;
  const text = $el.text().replace(/\u00a0/g, '').trim();
  return text === '';
}

// ── Main Pipeline ──────────────────────────────────────

/**
 * Clean raw HTML from a notice detail page for mobile rendering.
 *
 * 6-step pipeline:
 * 1. Junk element removal
 * 2. Inline style allowlist filtering
 * 3. Semantic tag normalization (inline elements only)
 * 4. URL absolute path conversion
 * 5. Tag allowlist via sanitize-html
 * 6. Empty element cleanup (including &nbsp;)
 */
export function cleanHtml(rawHtml: string, baseUrl: string): string | null {
  if (!rawHtml || rawHtml.trim() === '') return null;

  try {
    // Load as fragment (no html/body wrapper)
    const $ = cheerio.load(rawHtml, null, false);

    // ── Step 1: Junk element removal ─────────────────
    for (const sel of REMOVE_SELECTORS) {
      $(sel).remove();
    }

    // ── Step 2: Inline style allowlist ───────────────
    $('[style]').each((_i, el) => {
      const $el = $(el);
      const raw = $el.attr('style') || '';
      const filtered = filterStyles(raw);
      if (filtered) {
        $el.attr('style', filtered);
      } else {
        $el.removeAttr('style');
      }
    });

    // ── Step 3: Semantic tag normalization ────────────
    // Only convert font-weight/font-style on inline elements
    $('[style]').each((_i, el) => {
      const $el = $(el);
      const tagName = (el as Element).tagName?.toLowerCase();
      if (!tagName || !INLINE_ELEMENTS.has(tagName)) return;

      let style = $el.attr('style') || '';

      // font-weight: bold / 700 → <strong>
      const fw = getStyleProp(style, 'font-weight');
      if (fw && (fw === 'bold' || fw === '700')) {
        $el.wrapInner('<strong></strong>');
        style = removeStyleProp(style, 'font-weight');
      }

      // font-style: italic → <em>
      const fs = getStyleProp(style, 'font-style');
      if (fs && fs === 'italic') {
        $el.wrapInner('<em></em>');
        style = removeStyleProp(style, 'font-style');
      }

      // Update or remove style attribute
      const trimmed = style.replace(/;\s*$/, '').trim();
      if (trimmed) {
        $el.attr('style', trimmed);
      } else {
        $el.removeAttr('style');
      }
    });

    // ── Step 4: URL absolute path conversion ─────────
    $('img[src]').each((_i, el) => {
      const $el = $(el);
      const src = $el.attr('src');
      if (src) {
        $el.attr('src', resolveUrl(src, baseUrl));
      }
    });

    $('a[href]').each((_i, el) => {
      const $el = $(el);
      const href = $el.attr('href');
      if (href) {
        $el.attr('href', resolveUrl(href, baseUrl));
      }
    });

    // ── Step 5: Tag allowlist via sanitize-html ──────
    const serialized = $.html();
    const sanitized = sanitize(serialized, SANITIZE_CONFIG);

    // ── Step 6: Empty element cleanup ────────────────
    const $clean = cheerio.load(sanitized, null, false);

    for (let pass = 0; pass < MAX_EMPTY_PASSES; pass++) {
      let changed = false;
      $clean(REMOVABLE_EMPTY).each((_i, el) => {
        const $el = $clean(el);
        if (isEffectivelyEmpty($el)) {
          $el.remove();
          changed = true;
        }
      });
      if (!changed) break;
    }

    // Final check: if result is empty/whitespace-only, return null
    const result = $clean.html();
    if (!result || result.replace(/\u00a0/g, '').trim() === '') return null;

    return result;
  } catch (err) {
    logger.warn({ error: (err as Error).message }, 'cleanHtml pipeline failed');
    return null;
  }
}
