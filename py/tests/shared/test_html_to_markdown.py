"""Unit tests for `html_to_markdown.html_to_markdown`.

Covers the 6 cleanHtml patterns we captured from real dev-DB samples plus
targeted checks for the preprocessing passes (box unwrap, header promotion,
cell flatten) and basic line-break behaviour.
"""

from __future__ import annotations

from skkuverse_crawler.shared.html_cleaner import clean_html
from skkuverse_crawler.shared.html_to_markdown import html_to_markdown

BASE = "https://www.skku.edu/skku/campus/skk_comm/notice.do"


# ── Passthrough ────────────────────────────────────────

def test_none_passthrough():
    assert html_to_markdown(None) is None


def test_empty_string_passthrough():
    assert html_to_markdown("") == ""


# ── Line breaks ────────────────────────────────────────

def test_consecutive_paragraphs_have_blank_line():
    md = html_to_markdown("<p>First</p><p>Second</p>")
    assert md is not None
    assert md == "First\n\nSecond"


def test_br_inside_paragraph_becomes_line_break():
    md = html_to_markdown("<p>Line one<br>Line two</p>")
    assert md is not None
    # markdownify emits "  \n" (two spaces + newline) as GFM hard break
    assert "Line one" in md
    assert "Line two" in md
    assert md.index("Line one") < md.index("Line two")
    assert "Line one  \nLine two" in md or "Line one\nLine two" in md


def test_div_boundary_produces_line_break():
    md = html_to_markdown("<div>Alpha</div><div>Beta</div>")
    assert md is not None
    # Different divs should end up on different lines
    lines = [ln for ln in md.split("\n") if ln.strip()]
    assert "Alpha" in lines
    assert "Beta" in lines


# ── Headings, lists, images ────────────────────────────

def test_h3_conversion():
    md = html_to_markdown("<h3>제목</h3>")
    assert md == "### 제목"


def test_unordered_list():
    md = html_to_markdown("<ul><li>A</li><li>B</li></ul>")
    assert md is not None
    assert "- A" in md
    assert "- B" in md


def test_image_with_src():
    md = html_to_markdown('<p><img alt="poster" src="https://www.skku.edu/x.png"></p>')
    assert md is not None
    assert "![poster](https://www.skku.edu/x.png)" in md


def test_image_with_empty_alt():
    md = html_to_markdown('<p><img alt="" src="https://www.skku.edu/x.png"></p>')
    assert md is not None
    assert "https://www.skku.edu/x.png" in md


def test_link_conversion():
    md = html_to_markdown('<p>See <a href="https://skku.edu">here</a></p>')
    assert md is not None
    assert "[here](https://skku.edu)" in md


# ── Box table unwrap ───────────────────────────────────

def test_single_cell_box_table_unwrapped():
    html = (
        "<table><tbody><tr><td>"
        "<h3>공지 제목</h3>"
        "<p>본문 내용</p>"
        '<img alt="poster" src="https://www.skku.edu/p.png">'
        "</td></tr></tbody></table>"
    )
    md = html_to_markdown(html)
    assert md is not None
    # Table markup must be gone
    assert "|" not in md
    assert "---" not in md
    # Content must be preserved with structure
    assert "### 공지 제목" in md
    assert "본문 내용" in md
    assert "![poster](https://www.skku.edu/p.png)" in md


def test_colspan_box_table_unwrapped():
    html = (
        '<table><tbody><tr><td colspan="4">'
        "<h3>일정</h3>"
        "<div>4월 14일</div>"
        "</td></tr></tbody></table>"
    )
    md = html_to_markdown(html)
    assert md is not None
    assert "|" not in md
    assert "### 일정" in md
    assert "4월 14일" in md


# ── Header promotion ───────────────────────────────────

def test_header_promotion_bold_first_row():
    html = (
        "<table><tbody>"
        "<tr><td><strong>구분</strong></td><td><strong>일정</strong></td></tr>"
        "<tr><td>1차</td><td>5.13</td></tr>"
        "<tr><td>2차</td><td>5.27</td></tr>"
        "</tbody></table>"
    )
    md = html_to_markdown(html)
    assert md is not None
    # Expect a proper GFM table with a header separator under the bold row
    lines = md.strip().split("\n")
    assert any("**구분**" in ln and "**일정**" in ln for ln in lines)
    # Separator line should follow the header
    assert any("---" in ln and "|" in ln for ln in lines)
    # Data rows present
    assert any("1차" in ln and "5.13" in ln for ln in lines)


def test_header_not_promoted_when_body_all_bold():
    # Body entirely bolded — should NOT be promoted (would wrongly swallow content)
    html = (
        "<table><tbody>"
        "<tr><td><strong>A</strong></td><td><strong>B</strong></td></tr>"
        "<tr><td><strong>C</strong></td><td><strong>D</strong></td></tr>"
        "</tbody></table>"
    )
    md = html_to_markdown(html)
    assert md is not None
    # Header row should NOT be promoted — the separator should only appear
    # in markdownify's default position (empty header before first row)
    # Detection: the first non-empty row should not have been extracted as header
    # We mainly check the content survives; no crash, no content loss
    assert "A" in md and "B" in md and "C" in md and "D" in md


def test_header_not_promoted_for_single_row_table():
    html = (
        "<table><tbody>"
        "<tr><td><strong>only</strong></td></tr>"
        "</tbody></table>"
    )
    # This is a box table (tr=1, td=1) → should be unwrapped entirely
    md = html_to_markdown(html)
    assert md is not None
    assert "|" not in md
    assert "only" in md


# ── End-to-end with clean_html ─────────────────────────

def test_e2e_data_uri_stripped():
    raw = (
        '<p><img src="data:image/svg+xml;base64,AAA">'
        '<img src="https://www.skku.edu/real.png"></p>'
    )
    cleaned = clean_html(raw, BASE)
    md = html_to_markdown(cleaned)
    assert md is not None
    assert "data:" not in md
    assert "https://www.skku.edu/real.png" in md


def test_e2e_real_multi_row_table_header_promoted():
    raw = """
    <p>○ 일정</p>
    <table>
      <tbody>
        <tr>
          <td><p><strong>구분</strong></p></td>
          <td><strong>공문제출</strong></td>
          <td><strong>심의</strong></td>
        </tr>
        <tr><td>1차</td><td>5.13</td><td>5.14~5.19</td></tr>
        <tr><td>2차</td><td>5.27</td><td>5.28~6.2</td></tr>
      </tbody>
    </table>
    """
    cleaned = clean_html(raw, BASE)
    md = html_to_markdown(cleaned)
    assert md is not None
    assert "○ 일정" in md
    # Header row present with bold
    assert "**구분**" in md
    # GFM separator line
    assert "---" in md
    # Data rows present
    assert "1차" in md and "5.13" in md
    assert "2차" in md and "5.27" in md


def test_e2e_wordpress_download_box_div_chain_collapsed():
    raw = (
        "<div><div><div><div><div>"
        '<a href="https://cheme.skku.edu/file.pdf">졸업요건 안내</a>'
        "</div></div></div></div></div>"
    )
    cleaned = clean_html(raw, BASE)
    md = html_to_markdown(cleaned)
    assert md is not None
    assert "[졸업요건 안내](https://cheme.skku.edu/file.pdf)" in md


# ── <li> block flatten ─────────────────────────────────

def test_li_with_p_does_not_runaway_indent():
    # Each <li> contains <p> blocks. Without flattening, markdownify keeps
    # subsequent list items stuck under the bullet's indentation.
    html = (
        "<ul>"
        "<li><p>첫 줄</p><p>둘째 줄</p></li>"
        "<li>다음 항목</li>"
        "</ul>"
    )
    md = html_to_markdown(html)
    assert md is not None
    lines = md.split("\n")
    # Second item must appear at the same top-level bullet indent
    assert any(ln.startswith("- 다음 항목") for ln in lines)


def test_li_with_div_flattened():
    html = "<ul><li><div>안내</div>상세 내용</li></ul>"
    md = html_to_markdown(html)
    assert md is not None
    # Both pieces of text must be present and no deep indentation leak
    assert "안내" in md and "상세 내용" in md


def test_nested_ul_inside_li_preserved():
    # Direct <ul>/<ol> children of <li> must NOT be touched — they're
    # legitimate list nesting, not block-level bleed.
    html = "<ul><li>outer<ul><li>inner</li></ul></li></ul>"
    md = html_to_markdown(html)
    assert md is not None
    assert "- outer" in md
    # Nested item should still appear indented with its own bullet
    assert any("inner" in ln and ln.startswith((" ", "\t")) for ln in md.split("\n"))


# ── Tilde safety ───────────────────────────────────────

def test_tilde_in_prose_replaced_with_fullwidth():
    md = html_to_markdown("<p>14:00~17:00 / 7~8월</p>")
    assert md is not None
    assert "~" not in md
    assert "14:00～17:00" in md
    assert "7～8월" in md


def test_tilde_in_link_url_preserved():
    # Professor home URLs may legitimately contain ~. Must survive.
    md = html_to_markdown(
        '<p>See <a href="https://user.skku.edu/~prof/">here</a></p>'
    )
    assert md is not None
    assert "https://user.skku.edu/~prof/" in md
    # And literal `~` in the URL must not have been replaced
    assert "～prof" not in md


def test_tilde_in_image_url_preserved():
    md = html_to_markdown(
        '<p><img alt="x" src="https://user.skku.edu/~prof/a.png"></p>'
    )
    assert md is not None
    assert "https://user.skku.edu/~prof/a.png" in md


def test_double_tilde_becomes_fullwidth_not_strikethrough():
    # Even if source HTML injects ~~, we must not emit GFM strikethrough.
    md = html_to_markdown("<p>before~~middle~~after</p>")
    assert md is not None
    assert "~~" not in md
    assert "～～" in md


# ── Image dimension alt hint ───────────────────────────

def test_image_with_dimensions_embeds_alt_hint():
    md = html_to_markdown(
        '<p><img src="https://x/a.png" alt="포스터" width="800" height="600"></p>'
    )
    assert md is not None
    assert "![포스터 (800x600)](https://x/a.png)" in md


def test_image_with_only_width_no_leading_space_when_alt_empty():
    md = html_to_markdown(
        '<p><img src="https://x/a.png" alt="" width="800"></p>'
    )
    assert md is not None
    # No leading space inside the alt when alt was empty
    assert "![(w800)](https://x/a.png)" in md


def test_image_without_dimensions_bare_alt():
    md = html_to_markdown('<p><img src="https://x/a.png" alt="포스터"></p>')
    assert md is not None
    assert "![포스터](https://x/a.png)" in md


# ── Stray ** cleanup (safety net) ──────────────────────

def test_no_quad_asterisks_after_adjacent_strong():
    # clean_html also merges these, but verify html_to_markdown's
    # post-process safety net handles direct-input cases too.
    md = html_to_markdown("<p><strong>A</strong><strong>B</strong></p>")
    assert md is not None
    assert "****" not in md


def test_mixed_strong_b_cleanup_by_postprocess():
    # html_cleaner's merger groups by tag name, so <strong> + <b> can leak
    # through. The postprocess regex must still collapse the resulting `****`.
    md = html_to_markdown("<p><strong>A</strong><b>B</b></p>")
    assert md is not None
    assert "****" not in md


def test_postprocess_never_merges_paragraph_bolds():
    # Regression guard against an earlier _EMPTY_STRONG_RE = r"\*\*(\s*)\*\*"
    # bug where the regex matched across paragraph breaks and fused
    # `**A**\n\n**B**` into a single `**A\n\nB**` — a bold spanning two
    # paragraphs, which GFM parsers break on. Each paragraph's bold must
    # remain independently closed.
    md = html_to_markdown("<p><strong>A</strong></p><p><strong>B</strong></p>")
    assert md is not None
    # Both bolds present and closed within their own paragraph
    assert "**A**" in md
    assert "**B**" in md
    # No single bold spanning the blank line
    assert "**A\n\nB**" not in md


def test_postprocess_still_cleans_inline_empty_strong():
    # The tightened regex must still clean up whitespace-only strongs on a
    # single line (e.g. leftover `** **` from a <strong> </strong> wrapper
    # not caught by html_cleaner).
    md = html_to_markdown("<p>before** **after</p>")
    # The literal `** **` in prose isn't emitted by markdownify normally,
    # but we construct a minimal direct test of the postprocess layer by
    # checking the resulting string has no empty `** **` pair.
    assert md is not None
    assert "** **" not in md


# ── Tight-list normalization ───────────────────────────

def test_br_separated_bullets_become_tight_list():
    # The real-world skkumed M3 pattern: <p> with <br/>-separated lines
    # each starting with "- ". Must emit a tight list (no hard breaks
    # between items) so the mobile parser renders all as bullets.
    html = (
        "<p>- 5월 지급<br/>"
        "- 여름방학 연수<br/>"
        "- 8~9월 발표회</p>"
    )
    md = html_to_markdown(html)
    assert md is not None
    # All three items present at line start, no hard-break "  " trailing
    lines = md.split("\n")
    assert "- 5월 지급" in lines
    assert "- 여름방학 연수" in lines
    assert "- 8～9월 발표회" in lines  # tilde also replaced
    # None of the list lines should still carry a trailing hard-break
    for ln in lines:
        if ln.startswith("- "):
            assert not ln.endswith("  "), f"bullet line still has hard break: {ln!r}"


def test_mixed_bullet_and_prose_in_single_paragraph():
    # Ordered header followed by unordered bullets, all br-separated.
    # The hard breaks before every `- ` line must get stripped.
    html = (
        "<p>2. 유의사항<br/>"
        "- 공지된 바와 같이...<br/>"
        "- 프로그램 종료 후...</p>"
    )
    md = html_to_markdown(html)
    assert md is not None
    # `- 공지된` should appear at a new line with no leading "  " above
    assert r"2\. 유의사항" in md
    assert "- 공지된 바와 같이..." in md
    assert "- 프로그램 종료 후..." in md


def test_tight_list_fix_does_not_touch_hard_break_inside_paragraph():
    # A real intra-paragraph hard break (not before a bullet) must survive.
    html = "<p>line one<br/>line two</p>"
    md = html_to_markdown(html)
    assert md is not None
    # Hard break `  \n` between line one and line two is preserved
    assert "line one  \nline two" in md


def test_nbsp_after_dash_becomes_real_list():
    # The real-world medicine ASP notice shape: source HTML has a non-
    # breaking space after each `-` (from Word/HWP/Outlook export).
    # Before nbsp normalization, markdown parsers saw `-\xa0item` as prose
    # and only the one paragraph break-separated item became a list item,
    # so the mobile app rendered the last bullet differently from the rest.
    html = (
        "<p>-\u00a05월 지급<br/>"
        "-\u00a0여름방학 연수<br/>"
        "-\u00a08~9월 발표회</p>"
        "<p>-\u00a0해외 체류 중 유의</p>"
    )
    md = html_to_markdown(html)
    assert md is not None
    # All four items are now real list items (ASCII space after dash)
    assert "- 5월 지급" in md
    assert "- 여름방학 연수" in md
    assert "- 8～9월 발표회" in md  # tilde also replaced
    assert "- 해외 체류 중 유의" in md
    # No literal nbsp should remain
    assert "\u00a0" not in md
    # First three are tight (no hard-break separators leaking through)
    lines = md.split("\n")
    for ln in lines:
        if ln.startswith("- ") and "5월" in ln:
            assert not ln.endswith("  "), f"tight list leak: {ln!r}"


def test_nbsp_normalized_in_prose_text():
    md = html_to_markdown("<p>1.\u00a0일정\u00a0안내</p>")
    assert md is not None
    assert "\u00a0" not in md
    assert r"1\. 일정 안내" in md


# ── Underline stripped (no markdown equivalent) ───────

def test_underline_tag_stripped_text_preserved():
    md = html_to_markdown("<p>before <u>신청기한</u> after</p>")
    assert md is not None
    assert "신청기한" in md
    assert "<u>" not in md


def test_underline_tag_empty_content_dropped():
    md = html_to_markdown("<p>before <u>   </u> after</p>")
    assert md is not None
    assert "<u>" not in md


def test_underline_tag_mid_sentence_text_kept():
    md = html_to_markdown(
        "<p>원활한 간식 준비를 위해 <u>신청기한</u>을 반드시 준수해 주시기 바랍니다.</p>"
    )
    assert md is not None
    assert "신청기한을" in md or "신청기한 을" in md
    assert "<u>" not in md


# ── Ordered list escape ───────────────────────────────


def test_ordered_list_marker_escaped():
    """Bare '1. text' in a <p> should be escaped to prevent list rendering."""
    md = html_to_markdown("<p>1. 봉사활동 개요</p>")
    assert md is not None
    assert r"1\." in md
    # Should NOT render as a markdown list item
    assert not md.lstrip().startswith("1. ")


def test_multiple_numbered_lines_escaped():
    md = html_to_markdown(
        "<p>1. 첫 번째</p><p>2. 두 번째</p><p>3. 세 번째</p>"
    )
    assert md is not None
    assert r"1\." in md
    assert r"2\." in md
    assert r"3\." in md


def test_real_ol_converted_to_dash_bullets():
    """A real <ol><li> list should become '- ' bullets (ol→ul in preprocess)."""
    md = html_to_markdown("<ol><li>First</li><li>Second</li></ol>")
    assert md is not None
    assert "- First" in md
    assert "- Second" in md


# ── End-to-end: pre → cleanHtml → markdown ───────────


def test_nowon_notice_end_to_end():
    """노원평생학습한마당 notice: full pipeline produces correct markdown."""
    raw_html = (
        '<pre class="pre">서울시 노원평생학습관에서 자원봉사자를 모집합니다.\n\n'
        "1. 봉사활동 개요\n"
        " - 분야: 문화·체육·예술·관광\n"
        " - 대상: 대학생 15명\n\n"
        "2. 일시 및 장소\n"
        " - 일시: 2026.5.9.(토) 09:00～13:00\n\n"
        "3. 신청방법: 1365포털 검색\n\n"
        "4.  문의: 02-6958-8961</pre>\n"
        '<img alt="poster" src="https://www.skku.edu/img.png"/>'
    )
    base = "https://www.skku.edu/skku/campus/skk_comm/notice.do"
    cleaned = clean_html(raw_html, base)
    assert cleaned is not None

    md = html_to_markdown(cleaned)
    assert md is not None

    # Numbered items should be escaped — not rendered as list
    assert r"1\." in md
    assert r"4\." in md

    # Image should NOT be indented (not inside a list)
    for line in md.split("\n"):
        if "poster" in line:
            assert line.startswith("!"), f"Image line should not be indented: {line!r}"
            break

    # All content preserved
    assert "봉사활동 개요" in md
    assert "문의" in md
    assert "02-6958-8961" in md
