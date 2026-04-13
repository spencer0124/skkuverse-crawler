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


def test_small_data_uri_img_stripped():
    # Small data: URI (< 1 KB) — tracking pixel / spacer — should be removed
    html = (
        '<p><img alt="icon" src="   data:image/svg+xml;base64,AAA=">'
        '<img alt="real" src="https://www.skku.edu/foo.png"></p>'
    )
    result = clean_html(html, BASE)
    assert result is not None
    assert "data:" not in result
    assert "https://www.skku.edu/foo.png" in result


def test_large_data_uri_img_kept():
    # Large data: URI (>= 1 KB) — real content image — should be preserved
    # Generate a base64 payload > 1 KB decoded (need ~1400 base64 chars)
    big_b64 = "A" * 1400  # ~1050 bytes decoded
    html = (
        f'<p><img alt="poster" src="data:image/png;base64,{big_b64}">'
        '<img alt="real" src="https://www.skku.edu/foo.png"></p>'
    )
    result = clean_html(html, BASE)
    assert result is not None
    assert f"data:image/png;base64,{big_b64}" in result
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


# ── <pre> to paragraph conversion ─────────────────────


def test_pre_converted_to_paragraphs():
    """<pre> text lines should become <p> with <br> separators."""
    html = '<pre class="pre">Line A\nLine B\n\nLine C</pre>'
    result = clean_html(html, BASE)
    assert result is not None
    assert "<pre" not in result
    # Two paragraph groups: "Line A / Line B" and "Line C"
    assert "<p>" in result
    assert "Line A" in result
    assert "Line B" in result
    assert "Line C" in result


def test_pre_trailing_img_preserved():
    """<img> inside <pre> should survive as a sibling, not be lost."""
    html = (
        '<pre class="pre">Hello</pre>'
        '<img src="https://example.com/a.png" alt="pic"/>'
    )
    result = clean_html(html, BASE)
    assert result is not None
    assert "Hello" in result
    assert '<img' in result


def test_pre_nowon_notice_structure():
    """Real-world fixture: 노원평생학습한마당 notice preserves line breaks."""
    html = (
        '<pre class="pre">서울시 노원평생학습관\n\n'
        "1. 봉사활동 개요\n"
        " - 분야: 문화\n"
        " - 대상: 대학생\n\n"
        "2. 일시 및 장소\n"
        " - 일시: 2026.5.9.\n\n"
        "3. 신청방법: 포털 검색\n\n"
        "4.  문의: 02-6958-8961</pre>\n"
        '<img alt="poster" src="https://www.skku.edu/img.png"/>'
    )
    result = clean_html(html, BASE)
    assert result is not None
    assert "<pre" not in result
    # Each numbered section should be in its own <p>
    assert result.count("<p>") >= 4
    # Image should be outside paragraphs, not lost
    assert '<img' in result
