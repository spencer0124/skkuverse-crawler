/**
 * Unit tests for cleanHtml pipeline.
 * Run: npx tsx scripts/test-cleanhtml.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { cleanHtml } from '../src/notices/cleanHtml.js';

const BASE_URL = 'https://cse.skku.edu/cse/notice.do';

// ── Step 0: Edge cases ──────────────────────────────────

describe('Edge cases', () => {
  it('returns null for empty string', () => {
    assert.equal(cleanHtml('', BASE_URL), null);
  });

  it('returns null for whitespace-only string', () => {
    assert.equal(cleanHtml('   \n\t  ', BASE_URL), null);
  });

  it('returns null for null-like input', () => {
    assert.equal(cleanHtml(null as unknown as string, BASE_URL), null);
    assert.equal(cleanHtml(undefined as unknown as string, BASE_URL), null);
  });
});

// ── Step 1: Junk element removal ────────────────────────

describe('Step 1 — Junk element removal', () => {
  it('removes script, style, iframe, form, input, button', () => {
    const input = '<p>Hello</p><script>alert(1)</script><style>.x{}</style><iframe src="x"></iframe><form><input><button>Go</button></form>';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(!result.includes('<script'));
    assert.ok(!result.includes('<style'));
    assert.ok(!result.includes('<iframe'));
    assert.ok(!result.includes('<form'));
    assert.ok(!result.includes('<input'));
    assert.ok(!result.includes('<button'));
    assert.ok(result.includes('Hello'));
  });

  it('removes tfoot', () => {
    const input = '<table><tbody><tr><td>Data</td></tr></tbody><tfoot><tr><td>이전글</td></tr></tfoot></table>';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(!result.includes('이전글'));
    assert.ok(result.includes('Data'));
  });

  it('removes board-view selectors', () => {
    const input = '<div class="board-view-title-wrap">Title</div><p>Content</p><div class="board-view-file-wrap">Files</div><div class="board-view-nav">Nav</div>';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(!result.includes('board-view-title-wrap'));
    assert.ok(!result.includes('board-view-file-wrap'));
    assert.ok(!result.includes('board-view-nav'));
    assert.ok(result.includes('Content'));
  });

  it('removes mode=list links', () => {
    const input = '<p>Content</p><a href="?mode=list&articleLimit=10">목록</a>';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(!result.includes('목록'));
  });
});

// ── Step 2: Inline style allowlist ──────────────────────

describe('Step 2 — Inline style allowlist', () => {
  it('keeps color and drops font-family, font-size, margin, padding', () => {
    const input = `<span style="font-family: 'Noto Sans KR'; font-size: 14px; color: red; margin: 10px; padding: 5px;">Text</span>`;
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(result.includes('color'));
    assert.ok(!result.includes('font-family'));
    assert.ok(!result.includes('font-size'));
    assert.ok(!result.includes('margin'));
    assert.ok(!result.includes('padding'));
  });

  it('keeps text-align and background-color', () => {
    const input = '<p style="text-align: center; background-color: yellow; width: 600px;">Centered</p>';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(result.includes('text-align'));
    assert.ok(result.includes('background-color'));
    assert.ok(!result.includes('width'));
  });

  it('removes style attribute entirely when no allowed props remain', () => {
    const input = '<span style="font-family: Arial; font-size: 16px;">Text</span>';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(!result.includes('style'));
    assert.ok(result.includes('Text'));
  });
});

// ── Step 3: Semantic tag normalization ──────────────────

describe('Step 3 — Semantic tag normalization', () => {
  it('converts inline span font-weight:bold to <strong>', () => {
    const input = '<span style="font-weight: bold; color: red;">마감일</span>';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(result.includes('<strong>'));
    assert.ok(result.includes('마감일'));
    assert.ok(result.includes('color'));
  });

  it('converts inline span font-weight:700 to <strong>', () => {
    const input = '<span style="font-weight: 700;">Bold text</span>';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(result.includes('<strong>'));
    assert.ok(result.includes('Bold text'));
  });

  it('converts inline span font-style:italic to <em>', () => {
    const input = '<span style="font-style: italic;">Emphasis</span>';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(result.includes('<em>'));
    assert.ok(result.includes('Emphasis'));
  });

  it('keeps font-weight as style on block elements (div)', () => {
    const input = '<div style="font-weight: bold;">Block bold</div>';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(!result.includes('<strong>'));
    assert.ok(result.includes('font-weight'));
    assert.ok(result.includes('Block bold'));
  });

  it('keeps font-weight as style on block elements (p)', () => {
    const input = '<p style="font-weight: bold; color: blue;">Paragraph bold</p>';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(!result.includes('<strong>'));
    assert.ok(result.includes('font-weight'));
    assert.ok(result.includes('Paragraph bold'));
  });

  it('keeps text-decoration:underline as style (no conversion)', () => {
    const input = '<span style="text-decoration: underline;">Underlined</span>';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(result.includes('text-decoration'));
    assert.ok(result.includes('Underlined'));
  });
});

// ── Step 4: URL absolute path conversion ────────────────

describe('Step 4 — URL absolute path conversion', () => {
  it('resolves relative img src with leading slash', () => {
    const input = '<img src="/_res/editor_image/2026/03/photo.jpg">';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(result.includes('https://cse.skku.edu/_res/editor_image/2026/03/photo.jpg'));
  });

  it('resolves relative img src without leading slash', () => {
    const input = '<img src="img/photo.jpg">';
    const result = cleanHtml(input, BASE_URL)!;
    // new URL('img/photo.jpg', 'https://cse.skku.edu/cse/notice.do') → https://cse.skku.edu/cse/img/photo.jpg
    assert.ok(result.includes('https://cse.skku.edu/cse/img/photo.jpg'));
  });

  it('handles protocol-relative URLs', () => {
    const input = '<img src="//cdn.skku.edu/img.jpg">';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(result.includes('https://cdn.skku.edu/img.jpg'));
  });

  it('preserves data: URI images', () => {
    const input = '<img src="data:image/png;base64,abc123">';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(result.includes('data:image/png;base64,abc123'));
  });

  it('preserves already-absolute URLs', () => {
    const input = '<img src="https://example.com/photo.jpg">';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(result.includes('https://example.com/photo.jpg'));
  });

  it('resolves relative a[href]', () => {
    const input = '<a href="?mode=view&articleNo=123">Link</a>';
    const result = cleanHtml(input, BASE_URL)!;
    // & is HTML-encoded to &amp; in serialized output
    assert.ok(result.includes('https://cse.skku.edu/cse/notice.do?mode=view&amp;articleNo=123'));
  });
});

// ── Step 5: Tag allowlist ───────────────────────────────

describe('Step 5 — Tag allowlist', () => {
  it('strips disallowed tags but preserves content', () => {
    const input = '<marquee>Scrolling text</marquee><font color="red">Colored</font><center>Centered</center>';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(!result.includes('<marquee'));
    assert.ok(!result.includes('<font'));
    assert.ok(!result.includes('<center'));
    assert.ok(result.includes('Scrolling text'));
    assert.ok(result.includes('Colored'));
    assert.ok(result.includes('Centered'));
  });

  it('strips width attribute from table elements', () => {
    const input = '<table width="600"><tr><td width="300" colspan="2">Cell</td></tr></table>';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(!result.includes('width'));
    assert.ok(result.includes('colspan'));
    assert.ok(result.includes('Cell'));
  });
});

// ── Step 6: Empty element cleanup ───────────────────────

describe('Step 6 — Empty element cleanup', () => {
  it('removes empty p, span, div', () => {
    const input = '<p></p><span></span><div></div><p>Real content</p>';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(result.includes('Real content'));
    // Should not have empty wrapper elements
    assert.ok(!result.includes('<p></p>'));
    assert.ok(!result.includes('<span></span>'));
    assert.ok(!result.includes('<div></div>'));
  });

  it('removes elements containing only &nbsp;', () => {
    const input = '<p>&nbsp;</p><p>&nbsp;&nbsp;&nbsp;</p><p>Real content</p>';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(result.includes('Real content'));
    // The &nbsp;-only paragraphs should be removed
    const pCount = (result.match(/<p>/g) || []).length;
    assert.equal(pCount, 1, `Expected 1 <p> but found ${pCount} in: ${result}`);
  });

  it('preserves br, hr, img (void elements)', () => {
    const input = '<p>Text</p><br><hr><img src="https://example.com/photo.jpg">';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(result.includes('<br'));
    assert.ok(result.includes('<hr'));
    assert.ok(result.includes('<img'));
  });

  it('handles nested empty elements', () => {
    const input = '<div><p><span></span></p></div><p>Keep me</p>';
    const result = cleanHtml(input, BASE_URL)!;
    assert.ok(result.includes('Keep me'));
    assert.ok(!result.includes('<div><p><span></span></p></div>'));
  });

  it('returns null for content that becomes entirely empty after cleanup', () => {
    const input = '<p>&nbsp;</p><div><span></span></div>';
    const result = cleanHtml(input, BASE_URL);
    assert.equal(result, null);
  });
});

// ── End-to-end: Real SKKU HTML sample ───────────────────

describe('End-to-end', () => {
  it('transforms real SKKU cal-undergrad style HTML', () => {
    const input = `
      <span style="font-family: 'noto sans kr', 'Noto Sans KR', sans-serif; font-size: 14px; color: rgb(255, 0, 0); font-weight: bold; line-height: 1.8;">
        ※ 신청마감: 4월 7일(월) 13:00
      </span>
    `;
    const result = cleanHtml(input, BASE_URL)!;

    // Should have <strong> (from inline span bold conversion)
    assert.ok(result.includes('<strong>'), `Expected <strong> in: ${result}`);
    // Should have color preserved
    assert.ok(result.includes('color'), `Expected color in: ${result}`);
    // Should NOT have font-family, font-size, line-height
    assert.ok(!result.includes('font-family'), `Unexpected font-family in: ${result}`);
    assert.ok(!result.includes('font-size'), `Unexpected font-size in: ${result}`);
    assert.ok(!result.includes('line-height'), `Unexpected line-height in: ${result}`);
    // Content preserved
    assert.ok(result.includes('신청마감'), `Expected 신청마감 in: ${result}`);
  });

  it('handles mixed content with images, tables, and styles', () => {
    const input = `
      <div class="board-view-title-wrap">Should be removed</div>
      <p style="text-align: center;">
        <img src="/_res/img/poster.jpg" width="500" height="700">
      </p>
      <table width="600">
        <tr>
          <td colspan="2" style="font-family: Arial; color: blue;">
            <span style="font-weight: bold;">중요공지</span>
          </td>
        </tr>
      </table>
      <div class="board-view-file-wrap">Files section</div>
      <p>&nbsp;</p>
      <p>&nbsp;</p>
    `;
    const result = cleanHtml(input, BASE_URL)!;

    // Board wrappers removed
    assert.ok(!result.includes('Should be removed'));
    assert.ok(!result.includes('Files section'));
    // Image resolved to absolute
    assert.ok(result.includes('https://cse.skku.edu/_res/img/poster.jpg'));
    // Table width stripped
    assert.ok(!result.includes('width="600"'));
    // colspan preserved
    assert.ok(result.includes('colspan'));
    // td: font-family stripped, color kept
    assert.ok(!result.includes('font-family'));
    assert.ok(result.includes('color'));
    // Bold span converted to strong
    assert.ok(result.includes('<strong>'));
    assert.ok(result.includes('중요공지'));
    // Empty &nbsp; paragraphs removed
    const nbspParas = result.match(/<p>\s*(&nbsp;|\u00a0)\s*<\/p>/g);
    assert.equal(nbspParas, null, `Found &nbsp; paragraphs: ${nbspParas}`);
  });
});
