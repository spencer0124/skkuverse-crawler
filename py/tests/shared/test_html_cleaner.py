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
