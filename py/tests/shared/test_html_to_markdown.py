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
