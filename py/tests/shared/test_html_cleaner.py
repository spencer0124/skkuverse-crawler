"""Unit tests for the Phase-1 structural improvements in `html_cleaner.clean_html`.

These cover the four post-nh3 passes that were added to bring cleanHtml
closer to a shape the Markdown converter can work with:

1. Empty `<span>` unwrap
2. Single-child `<div>` chain collapse
3. Data URI `<img>` catch-all strip
4. font-weight `bolder` / `≥600` → `<strong>` normalization
"""

from __future__ import annotations

from skkuverse_crawler.shared.html_cleaner import clean_html

BASE = "https://www.skku.edu/skku/campus/skk_comm/notice.do"


def test_empty_span_unwrapped():
    html = '<p><span>hello</span> <span style="">world</span></p>'
    result = clean_html(html, BASE)
    assert result is not None
    assert "<span" not in result
    assert "hello" in result
    assert "world" in result


def test_single_child_div_chain_collapsed():
    # WordPress download-box style: nested single-child divs
    html = (
        "<div><div><div><div>"
        '<a href="https://cheme.skku.edu/file.pdf">파일</a>'
        "</div></div></div></div>"
    )
    result = clean_html(html, BASE)
    assert result is not None
    # At most one div should remain around the link (the innermost real content)
    assert result.count("<div>") <= 1
    assert 'href="https://cheme.skku.edu/file.pdf"' in result


def test_data_uri_img_stripped_with_whitespace():
    # Whitespace before the data: scheme — guards against step 1.5 selector misses
    html = (
        '<p><img alt="icon" src="   data:image/svg+xml;base64,AAA=">'
        '<img alt="real" src="https://www.skku.edu/foo.png"></p>'
    )
    result = clean_html(html, BASE)
    assert result is not None
    assert "data:" not in result
    assert "https://www.skku.edu/foo.png" in result


def test_font_weight_bolder_normalized_to_strong():
    html = '<p><span style="font-weight:bolder">경고</span></p>'
    result = clean_html(html, BASE)
    assert result is not None
    assert "<strong>경고</strong>" in result


def test_font_weight_numeric_600_normalized_to_strong():
    html = '<p><span style="font-weight:600">주의</span></p>'
    result = clean_html(html, BASE)
    assert result is not None
    assert "<strong>주의</strong>" in result


def test_font_weight_400_not_normalized():
    html = '<p><span style="font-weight:400">보통</span></p>'
    result = clean_html(html, BASE)
    assert result is not None
    # 400 = normal → should NOT become strong
    assert "<strong>" not in result
    assert "보통" in result


# ── Adjacent <strong> merge + punctuation strip ─────────

def test_adjacent_strongs_merged():
    html = "<p><strong>26</strong><strong>年 4월</strong></p>"
    result = clean_html(html, BASE)
    assert result is not None
    assert "<strong>26年 4월</strong>" in result
    # Verify only one strong tag remains (not two adjacent)
    assert result.count("<strong>") == 1


def test_adjacent_strongs_merged_across_whitespace():
    html = "<p><strong>A</strong> <strong>B</strong></p>"
    result = clean_html(html, BASE)
    assert result is not None
    # The whitespace bridge should be absorbed into the merged tag
    assert "<strong>A B</strong>" in result
    assert result.count("<strong>") == 1


def test_three_strongs_with_punct_middle_loses_middle_strong():
    # Real dev-DB pattern: `<strong>시험</strong><strong>·</strong><strong>과제물</strong>`
    # The middle strong is punctuation-only and gets unwrapped. The two real
    # strongs are NOT merged because `·` is a visible text bridge, not
    # whitespace — preserving this separation is the conservative choice.
    # What matters is that the markdown output no longer has `****` artifacts.
    html = "<p><strong>시험</strong><strong>·</strong><strong>과제물</strong></p>"
    result = clean_html(html, BASE)
    assert result is not None
    # Exactly the two real strongs remain, dot is plain text between them
    assert result.count("<strong>") == 2
    assert "<strong>시험</strong>·<strong>과제물</strong>" in result


def test_punctuation_only_strong_unwrapped():
    html = "<p><strong>[</strong><strong>기아] 모집</strong></p>"
    result = clean_html(html, BASE)
    assert result is not None
    # The bracket-only strong should be unwrapped, leaving the real one
    # with a `[` text sibling merged into it (since now adjacent via bridge).
    assert "<strong>[" not in result
    # The bracket survives as plain text + merged strong content
    assert "[" in result and "기아] 모집" in result


def test_non_adjacent_strongs_not_merged():
    html = "<p><strong>A</strong>text<strong>B</strong></p>"
    result = clean_html(html, BASE)
    assert result is not None
    # Real text between them — must NOT merge
    assert result.count("<strong>") == 2


# ── Word-exported head-only tag bleed ──────────────────

def test_inline_title_tag_removed_with_text():
    # Real pattern from skkumed ASP boards: Word-exported content embeds
    # <title>제목없음</title> as a sibling of body <p> blocks. nh3 alone
    # strips the tag but keeps the text child — must be decomposed.
    html = (
        "<p></p><title>제목없음</title>"
        '<meta charset="utf-8">'
        "<p>실제 본문</p>"
    )
    result = clean_html(html, BASE)
    assert result is not None
    assert "제목없음" not in result
    assert "실제 본문" in result
    assert "<title" not in result
    assert "<meta" not in result


def test_inline_link_tag_removed():
    html = '<link rel="stylesheet" href="x.css"><p>hello</p>'
    result = clean_html(html, BASE)
    assert result is not None
    assert "<link" not in result
    assert "hello" in result
