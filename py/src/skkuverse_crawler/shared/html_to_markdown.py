"""cleanHtml → Markdown converter.

This module consumes the output of `clean_html()` (an nh3-sanitized HTML
string with ~20 allowlisted tags) and produces a Markdown string suitable
for mobile rendering.

Two problems in SKKU notice HTML require preprocessing before handing it
to markdownify:

1. **Layout tables** (`tr=1 && td=1`): SKKU boards wrap entire notice
   bodies in a single-cell `<table>` for styling. markdownify collapses
   their block structure into one GFM row, losing headings, images, and
   paragraph breaks. We detect and unwrap them.

2. **Headerless data tables** (`<thead>/<th>` are never emitted): real
   multi-row tables use plain `<tr><td>` with the first row bolded.
   markdownify renders those as a table with an empty header row, so we
   promote all-bold first rows to `<thead><th>` when the second row is
   *not* all-bold (to avoid false positives on bodies of bold text).

See `tests/shared/test_html_to_markdown.py` for fixture-based examples.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString, Tag
from markdownify import MarkdownConverter

from .logger import get_logger

logger = get_logger("html_to_markdown")


# ── Preprocessing ──────────────────────────────────────

def _unwrap_box_tables(soup: BeautifulSoup) -> None:
    """Replace layout wrapper tables with their cell contents.

    A table is a "box" if every ``<tr>`` has exactly one ``<td>``/``<th>``
    (single-column layout table).  This covers the common 1-row-1-cell
    wrapper **and** multi-row single-column layout tables that Naver
    SmartEditor and similar WYSIWYG editors produce (after class info has
    been stripped by nh3).
    """
    for table in list(soup.find_all("table")):
        trs = table.find_all("tr")
        if not trs:
            continue
        if not all(len(tr.find_all(["td", "th"])) == 1 for tr in trs):
            continue
        for tr in trs:
            cell = tr.find_all(["td", "th"])[0]
            for child in list(cell.children):
                if isinstance(child, (Tag, NavigableString)):
                    table.insert_before(child.extract())
        table.decompose()


def _cell_is_all_bold(cell: Tag) -> bool:
    """True when every non-whitespace character in `cell` is inside `<strong>`/`<b>`."""
    total = cell.get_text(strip=True)
    if not total:
        return False
    bold_text = "".join(s.get_text() for s in cell.find_all(["strong", "b"]))
    return "".join(bold_text.split()) == "".join(total.split())


def _promote_header_rows(soup: BeautifulSoup) -> None:
    """Convert bold first rows to `<thead><th>` so GFM rendering keeps a header.

    Triggers when:
    - The table has ≥2 rows (avoid single-row tables that should be handled
      as box layouts or flattened).
    - Every cell in the first row is all-bold.
    - The second row is **not** all-bold (guards against notices whose body
      is entirely bolded).
    """
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if len(trs) < 2:
            continue
        first_cells = trs[0].find_all(["td", "th"])
        if not first_cells:
            continue
        if not all(_cell_is_all_bold(c) for c in first_cells):
            continue
        second_cells = trs[1].find_all(["td", "th"])
        if second_cells and all(_cell_is_all_bold(c) for c in second_cells):
            continue

        for td in list(first_cells):
            if td.name == "th":
                continue
            th = soup.new_tag("th")
            for key in ("colspan", "rowspan"):
                if td.get(key):
                    th[key] = td[key]
            for child in list(td.children):
                if isinstance(child, (Tag, NavigableString)):
                    th.append(child.extract())
            td.replace_with(th)
        thead = soup.new_tag("thead")
        trs[0].wrap(thead)


def _has_prev_inline_content(tag: Tag) -> bool:
    prev = tag.previous_sibling
    while prev is not None:
        if isinstance(prev, Tag):
            if prev.name in ("img", "br") or prev.get_text(strip=True):
                return True
        elif str(prev).strip():
            return True
        prev = prev.previous_sibling
    return False


def _flatten_cell_blocks(soup: BeautifulSoup) -> None:
    """Unwrap `<p>`/`<div>` inside table cells, inserting `<br>` between siblings.

    markdownify renders block elements inside `<td>` as inline text with no
    separator, so cell contents get glued together. Replacing the blocks
    with `<br>` preserves visual line breaks inside the cell.
    """
    for cell in soup.find_all(["td", "th"]):
        for block in list(cell.find_all(["p", "div"])):
            if _has_prev_inline_content(block):
                block.insert_before(soup.new_tag("br"))
            block.unwrap()


def _normalize_nbsp(soup: BeautifulSoup) -> None:
    """Replace U+00A0 (non-breaking space) with regular space in text nodes.

    Word / HWP / Outlook notices embed `&nbsp;` as layout padding, which
    parses into literal `\\xa0` characters in BeautifulSoup text nodes.
    Markdown list markers require ASCII space after `-`, so a source line
    like `-\\xa05월` is NOT recognized as a bullet by any parser — it stays
    literal text, causing the whole br-separated pseudo-list to degrade to
    prose. Normalizing nbsp to regular space lets markdownify emit real
    `- item` lines, and downstream postprocess (hard-break stripping,
    tight-list detection) can then work as intended.

    We only touch NavigableString nodes, not attribute values, so URL and
    style attributes are untouched.
    """
    for node in list(soup.find_all(string=True)):
        raw = str(node)
        if "\u00a0" in raw:
            node.replace_with(NavigableString(raw.replace("\u00a0", " ")))


def _flatten_li_blocks(soup: BeautifulSoup) -> None:
    """Unwrap `<p>`/`<div>` that are direct children of `<li>`.

    When a list item contains block elements, markdownify keeps subsequent
    items (and even the content *after* the list) stuck under the bullet's
    indentation — the bullet ends up "swallowing" its siblings. Flattening
    direct-child blocks to inline text (separated by `<br>` where needed)
    lets markdownify emit a clean single-line list item.

    We only touch *direct* children so that legitimate nested `<ul>`/`<ol>`
    structure is left alone.
    """
    for li in soup.find_all("li"):
        for child in list(li.children):
            if not isinstance(child, Tag):
                continue
            if child.name in ("p", "div"):
                if _has_prev_inline_content(child):
                    child.insert_before(soup.new_tag("br"))
                child.unwrap()


_BULLET_PREFIX_RE = re.compile(r"^[·●○▶▷◆◇※►•]\s*")


def _convert_pseudo_bullets(soup: BeautifulSoup) -> None:
    """Convert consecutive ``<p>`` elements starting with bullet chars to ``<ul><li>``.

    Korean notices commonly use middle-dot (·) or other symbols as pseudo-
    bullets inside ``<p>`` tags.  markdownify treats these as prose paragraphs
    with double newlines between them, creating excessive spacing.  Converting
    to semantic ``<ul><li>`` produces tight markdown lists.

    Only fires when 2+ consecutive bullet paragraphs are found to avoid
    false positives on isolated bullet-like text.
    """
    processed: set[int] = set()
    for p in list(soup.find_all("p")):
        if id(p) in processed or p.parent is None:
            continue
        text = p.get_text()
        if not text or not _BULLET_PREFIX_RE.match(text.strip()):
            continue

        # Collect consecutive bullet <p> siblings
        run: list[Tag] = [p]
        nxt = p.next_sibling
        while nxt is not None:
            if isinstance(nxt, NavigableString) and not nxt.strip():
                nxt = nxt.next_sibling
                continue
            if isinstance(nxt, Tag) and nxt.name == "p":
                nxt_text = nxt.get_text()
                if nxt_text and _BULLET_PREFIX_RE.match(nxt_text.strip()):
                    run.append(nxt)
                    nxt = nxt.next_sibling
                    continue
            break

        if len(run) < 2:
            continue

        ul = soup.new_tag("ul")
        p.insert_before(ul)
        for bp in run:
            processed.add(id(bp))
            li = soup.new_tag("li")
            for child in list(bp.children):
                li.append(child.extract())
            # Strip the bullet prefix from the first text node
            first_text = li.find(string=True)
            if first_text:
                cleaned = _BULLET_PREFIX_RE.sub("", str(first_text), count=1)
                first_text.replace_with(NavigableString(cleaned))
            ul.append(li)
            bp.decompose()


def _preprocess(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    # nbsp normalization must run first so downstream passes see ASCII
    # spaces in text (e.g. `- item` where Word dropped `-\xa0item`).
    _normalize_nbsp(soup)
    _convert_pseudo_bullets(soup)
    _unwrap_box_tables(soup)
    _promote_header_rows(soup)
    _flatten_cell_blocks(soup)
    _flatten_li_blocks(soup)
    return str(soup)


# ── Conversion ─────────────────────────────────────────

_MULTIBLANK_RE = re.compile(r"\n{3,}")
# `[ \t]*` — spaces/tabs only, NEVER newlines. An earlier version used `\s*`,
# which matched across paragraph breaks and catastrophically merged
# `**A**\n\n**B**` into `**A\n\nB**` (one bold spanning two paragraphs).
# This regex is only meant to clean single-line `** **` artifacts from
# `<strong>` tags that wrap whitespace; cross-line strongs must never be
# collapsed because each paragraph's bold is semantically independent.
_EMPTY_STRONG_RE = re.compile(r"\*\*([ \t]*)\*\*")
_REPEATED_STRONG_RE = re.compile(r"\*{3,}")            # *** or more → **
# Strip hard-break (`  \n`) before a `- ` bullet line so br-separated
# pseudo-lists become tight real lists. Medicine ASP notices use
# `<p>- a<br>- b<br>- c</p>`, which markdownify emits as
# `- a  \n- b  \n- c`; strict parsers then treat the dashes as literal
# text inside one paragraph instead of a bullet list. Removing the two
# trailing spaces turns it into `- a\n- b\n- c`, a tight list every GFM
# parser recognizes. The lookahead keeps this surgical: only fires when
# the next line is itself a bullet.
_HARDBREAK_BEFORE_BULLET_RE = re.compile(r"[ \t]{2,}\n(?=- )")
# Same idea for a trailing hard-break immediately before a blank line
# (the last item of a br-separated pseudo-list): the hard break has no
# visible effect and just confuses list termination heuristics.
_HARDBREAK_BEFORE_BLANK_RE = re.compile(r"[ \t]{2,}\n(?=\n)")


def _escape_md_alt(text: str) -> str:
    """Minimal escaping for alt text so `[`/`]` don't break the image syntax."""
    return text.replace("[", "\\[").replace("]", "\\]")


class _SkkuMarkdownConverter(MarkdownConverter):
    """markdownify converter with handlers for dimensions and underline.

    Two extensions over the default:

    1. **Image dimensions via alt hint.** Standard markdown has no syntax
       for image size. GFM technically allows raw HTML `<img width height>`
       to pass through, but we can't rely on the mobile renderer to accept
       inline HTML for `<img>` yet, so we encode dimensions as `(WxH)`
       appended to the alt text:

           ![포스터 (800x600)](https://.../a.png)

       TODO: switch to `<img src alt width height />` once the app supports
       raw-HTML passthrough in markdown.

    """

    def convert_img(self, el, text, parent_tags):  # type: ignore[override]
        alt = el.attrs.get("alt", "") or ""
        src = el.attrs.get("src", "") or ""
        title = el.attrs.get("title", "")
        width = el.attrs.get("width")
        height = el.attrs.get("height")

        if width and height:
            dim_hint = f"({width}x{height})"
        elif width:
            dim_hint = f"(w{width})"
        elif height:
            dim_hint = f"(h{height})"
        else:
            dim_hint = ""

        alt_escaped = _escape_md_alt(alt)
        if alt_escaped and dim_hint:
            alt_final = f"{alt_escaped} {dim_hint}"
        else:
            alt_final = alt_escaped or dim_hint

        title_part = f' "{title}"' if title else ""
        return f"![{alt_final}]({src}{title_part})"


def _replace_tildes_safely(md: str) -> str:
    """Replace `~` with `～` (U+FF5E) outside code spans and link/image URLs.

    GFM renders `~~text~~` as strikethrough. Korean notices use `~` heavily
    for date/time ranges (`14:00~17:00`, `7~8월`), which are at constant
    risk of collision. The full-width wave dash is visually near-identical
    and carries zero markdown semantics.

    We deliberately skip two regions so URLs and inline code survive intact:
      - inline code spans: matched runs of backticks
      - markdown link/image URL part: `](` up to the matching `)`
    """
    out: list[str] = []
    i = 0
    n = len(md)
    while i < n:
        ch = md[i]

        # Inline code span — find opening run, then a closing run of same length
        if ch == "`":
            j = i
            while j < n and md[j] == "`":
                j += 1
            run = md[i:j]
            close = md.find(run, j)
            if close == -1:
                # Unmatched backticks: treat as literal, keep scanning after them
                out.append(run)
                i = j
                continue
            out.append(md[i : close + len(run)])
            i = close + len(run)
            continue

        # Link/image URL part: `](` ... `)` (with nested-paren tolerance)
        if ch == "]" and i + 1 < n and md[i + 1] == "(":
            out.append("](")
            i += 2
            depth = 1
            while i < n and depth > 0:
                c2 = md[i]
                out.append(c2)
                i += 1
                if c2 == "(":
                    depth += 1
                elif c2 == ")":
                    depth -= 1
                    if depth == 0:
                        break
            continue

        if ch == "~":
            out.append("～")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _postprocess(md: str) -> str:
    # Step 0: per-line whitespace normalization.
    #   - whitespace-only lines → empty blank line
    #   - content + 2+ trailing spaces → content + exactly 2 spaces (GFM hard break)
    #   - content + other trailing whitespace → stripped
    # This has to run FIRST so the subsequent regexes see canonical blank
    # lines (`\n\n`) instead of `  \n  \n` — without this, the hard-break
    # cleanup regexes silently fail because their lookaheads expect a
    # literal `\n` right after the hard break, not a whitespace-only line.
    out_lines: list[str] = []
    for line in md.split("\n"):
        content = line.rstrip()
        if not content:
            out_lines.append("")
        elif line.endswith("  "):
            out_lines.append(content + "  ")
        else:
            out_lines.append(content)
    md = "\n".join(out_lines)

    # Collapse runs of 3+ newlines to a single paragraph break.
    md = _MULTIBLANK_RE.sub("\n\n", md)

    # Strip stray `**` artifacts. The html_cleaner adjacent-strong merge
    # catches the common case, but <strong> adjacent to <b> (or nested
    # wrappers) can still leak here. Idempotent safety net.
    md = _EMPTY_STRONG_RE.sub(r"\1", md)       # `** **` on one line → ` `
    md = _REPEATED_STRONG_RE.sub("**", md)     # `***` / `****` → `**`

    # Normalize br-separated pseudo-list bullets into tight lists. Must
    # run after step 0 (so blank lines are canonical) and before tilde
    # replacement (so the lookaheads still match `- `).
    md = _HARDBREAK_BEFORE_BULLET_RE.sub("\n", md)
    md = _HARDBREAK_BEFORE_BLANK_RE.sub("\n", md)

    # Neutralize GFM strikethrough risk from `~` in prose.
    md = _replace_tildes_safely(md)

    return md.strip()


def html_to_markdown(clean_html_str: str | None) -> str | None:
    """Convert sanitized cleanHtml to GitHub-flavored Markdown.

    Returns `None` when input is `None`, `""` when input is empty, or the
    converted string otherwise. On unexpected errors we log and return
    `None` so callers fall back to `cleanHtml`/`contentText` paths.
    """
    if clean_html_str is None:
        return None
    if clean_html_str == "":
        return ""
    try:
        preprocessed = _preprocess(clean_html_str)
        md = _SkkuMarkdownConverter(
            heading_style="ATX",
            bullets="-",
            strong_em_symbol="*",
            autolinks=True,
            newline_style="SPACES",
        ).convert(preprocessed)
        return _postprocess(md)
    except Exception as exc:
        logger.warning("html_to_markdown_failed", error=str(exc))
        return None
