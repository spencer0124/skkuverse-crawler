from __future__ import annotations

from urllib.parse import urljoin

import nh3
from bs4 import BeautifulSoup, NavigableString, Tag

from .logger import get_logger

logger = get_logger("html_cleaner")

# ── Constants ──────────────────────────────────────────

# Step 1: Selectors for junk elements to remove
REMOVE_SELECTORS = [
    "script", "style", "iframe", "form", "input", "button",
    "tfoot",
    # Head-only tags that occasionally get dropped inline by Word-exported
    # HTML (skkumed ASP boards in particular). nh3 would strip the tag but
    # keep the text child of <title>, leaking strings like "제목없음" into
    # the rendered body — decompose here before nh3 ever sees it.
    "title", "meta", "link", "head",
    ".board-view-title-wrap",
    ".board-view-file-wrap",
    ".board-view-nav",
    'a[href*="mode=list"]',
]

# Step 2: Only inline elements get font-weight→<strong> / font-style→<em>
INLINE_ELEMENTS = frozenset([
    "span", "a", "font", "b", "i", "em", "strong", "mark",
])

# Step 4: nh3 configuration
ALLOWED_TAGS = {
    "p", "br", "div", "span", "h1", "h2", "h3", "h4",
    "strong", "b", "em", "i", "mark",
    "ul", "ol", "li",
    "table", "thead", "tbody", "tr", "th", "td",
    "img", "a", "hr",
}

ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "*": {"style"},
    "a": {"href"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}

ALLOWED_STYLE_PROPERTIES = {
    "color", "background-color", "text-align", "text-decoration",
    "font-weight", "font-style",
}

ALLOWED_URL_SCHEMES = {"http", "https", "mailto", "tel"}

# Step 5: Elements to check for emptiness
REMOVABLE_EMPTY_TAGS = {
    "p", "span", "div", "strong", "b", "em", "i", "mark",
    "h1", "h2", "h3", "h4", "a", "li", "td", "th", "tr",
    "thead", "tbody", "table", "ul", "ol",
}

MAX_EMPTY_PASSES = 10


# ── Helpers ────────────────────────────────────────────

def _get_style_prop(style_str: str, prop: str) -> str | None:
    for decl in style_str.split(";"):
        colon = decl.find(":")
        if colon == -1:
            continue
        if decl[:colon].strip().lower() == prop:
            return decl[colon + 1:].strip()
    return None


def _remove_style_prop(style_str: str, prop: str) -> str:
    parts = []
    for decl in style_str.split(";"):
        trimmed = decl.strip()
        colon = trimmed.find(":")
        if colon == -1:
            continue
        if trimmed[:colon].strip().lower() != prop:
            parts.append(trimmed)
    return "; ".join(parts)


def _resolve_url(relative: str, base: str) -> str:
    if not relative:
        return relative
    if relative.startswith(("data:", "mailto:", "tel:")):
        return relative
    try:
        return urljoin(base, relative)
    except Exception:
        return relative


def _is_effectively_empty(tag: Tag) -> bool:
    # Has child elements (not just NavigableString) → not empty
    if tag.find(True):
        return False
    text = tag.get_text().replace("\u00a0", "").strip()
    return text == ""


def _is_bold_weight(fw: str) -> bool:
    """True if a CSS `font-weight` value means bold.

    Matches keywords (`bold`, `bolder`) and numeric values 600 and above.
    """
    value = fw.strip().lower()
    if value in ("bold", "bolder"):
        return True
    if value.isdigit():
        try:
            return int(value) >= 600
        except ValueError:
            return False
    return False


def _unwrap_empty_spans(soup: BeautifulSoup) -> None:
    """Remove `<span>` tags with no remaining attributes.

    nh3 strips disallowed style properties, which often leaves `<span>` with
    an empty style attribute or no attributes at all — wrappers that email
    composers scatter through copy-pasted notices. Unwrapping keeps their
    text content in place.
    """
    for span in list(soup.find_all("span")):
        style = span.get("style")
        if isinstance(style, str) and style.strip() == "":
            del span["style"]
        if not span.attrs:
            span.unwrap()


def _collapse_single_child_div_chains(soup: BeautifulSoup, max_passes: int = 5) -> None:
    """Collapse chains of `<div>` that each wrap exactly one block child.

    WordPress download-box markup renders as 6–9 nested `<div>` wrappers
    around a single file card. After nh3 strips classes/styles there is no
    semantic information left in those wrappers, so unwrap them until the
    structure stabilises.
    """
    for _ in range(max_passes):
        changed = False
        for div in list(soup.find_all("div")):
            if div.parent is None:
                continue
            children = [
                c for c in div.children
                if not (isinstance(c, str) and not c.strip())
            ]
            if len(children) != 1:
                continue
            only = children[0]
            if isinstance(only, Tag) and only.name == "div":
                div.unwrap()
                changed = True
        if not changed:
            break


def _convert_pre_to_paragraphs(soup: BeautifulSoup) -> None:
    """Replace ``<pre>`` blocks with ``<p>`` + ``<br>`` elements.

    ``<pre>`` is not in ``ALLOWED_TAGS``, so nh3 strips the wrapper and
    leaves raw text with literal ``\\n``.  That text then leaks into
    markdown as accidental list syntax (``1. ``, ``- ``).

    This function converts each ``<pre>`` before nh3 runs:
      - Split text on blank lines (``\\n\\n``) → separate ``<p>`` elements
      - Single ``\\n`` within a paragraph → ``<br>``
    Non-text children (e.g. ``<img>`` after the text) are preserved as
    siblings after the converted paragraphs.
    """
    for pre in soup.find_all("pre"):
        text = pre.get_text()
        if not text or not text.strip():
            pre.unwrap()
            continue

        # Collect any non-text children (images, links, etc.) to re-append
        trailing_tags = [
            child.extract()
            for child in list(pre.children)
            if isinstance(child, Tag)
        ]

        # Split on blank lines for paragraph groups
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            pre.unwrap()
            continue

        # Build replacement elements
        new_elements: list[Tag] = []
        for para_text in paragraphs:
            p = soup.new_tag("p")
            lines = para_text.split("\n")
            for i, line in enumerate(lines):
                if i > 0:
                    p.append(soup.new_tag("br"))
                p.append(NavigableString(line))
            new_elements.append(p)

        # Replace <pre> with the new <p> elements + trailing tags
        for elem in new_elements:
            pre.insert_before(elem)
        for tag in trailing_tags:
            pre.insert_before(tag)
        pre.decompose()


def _unwrap_naver_smarteditor_tables(soup: BeautifulSoup) -> None:
    """Unwrap Naver SmartEditor layout tables (class ``__se_tbl_ext``).

    SmartEditor wraps content in deeply nested layout tables for visual
    formatting.  These are not data tables — each cell typically contains
    prose or images.  Replace each table with the concatenated contents
    of all its cells in document order.
    """
    for table in list(soup.select("table.__se_tbl_ext")):
        for cell in table.find_all(["td", "th"]):
            for child in list(cell.children):
                table.insert_before(child.extract())
        table.decompose()


def _strip_data_uri_images(soup: BeautifulSoup) -> None:
    """Remove `<img>` tags whose `src` is a data URI.

    Step 1.5's CSS selector `img[src^='data:']` can miss cases where the
    attribute value has leading whitespace or odd quoting, so we do a
    defensive pass on the serialized soup right before returning.
    """
    for img in list(soup.find_all("img")):
        src = img.get("src", "")
        if isinstance(src, str) and src.lstrip().lower().startswith("data:"):
            img.decompose()


# CJK punctuation that should count as "punctuation-only" content. ASCII
# punctuation/whitespace is already handled by `string.punctuation`/`string.whitespace`.
_CJK_PUNCTUATION = "（）［］【】「」『』〈〉《》〔〕、，。：；！？·～—–"


def _strip_punctuation_only_inline(
    soup: BeautifulSoup,
    tag_names: tuple[str, ...] = ("strong", "b", "em", "i"),
) -> None:
    """Unwrap inline emphasis tags whose text is only whitespace/punctuation.

    WYSIWYG editors often wrap a single bracket or bullet (`<strong>[</strong>`,
    `<strong>·</strong>`) which markdownify then renders as the visually broken
    `**[**` / `**·**`. Since the bold has no semantic value there, we simply
    unwrap it. Running this *before* adjacent-strong merging also lets the
    real bold runs on either side of the bracket become siblings.
    """
    import string

    skip = set(
        string.whitespace + string.punctuation + string.digits + _CJK_PUNCTUATION
    )
    for tag in list(soup.find_all(tag_names)):
        if tag.find(True):  # skip if it contains child elements
            continue
        text = tag.get_text()
        if not text or not all(ch in skip for ch in text):
            continue
        # Pure digits (e.g. "26") may be intentional emphasis; only
        # strip when mixed with punctuation (e.g. "1.", "3)").
        if text.strip().isdigit():
            continue
        tag.unwrap()


def _strip_sole_child_bold(soup: BeautifulSoup) -> None:
    """Unwrap <strong>/<b> in runs of 3+ consecutive all-bold block siblings.

    When a WYSIWYG editor wraps every paragraph in bold, every line
    becomes ``**text**`` in markdown — visually noisy and semantically
    meaningless.  A single ``<p><strong>title</strong></p>`` may be
    intentional emphasis, so we only strip when 3+ consecutive sibling
    blocks are ALL sole-child bold (bulk WYSIWYG artifact).
    """
    _MIN_RUN = 3

    def _is_sole_bold(block: Tag) -> bool:
        children = [
            c
            for c in block.children
            if not (isinstance(c, NavigableString) and not c.strip())
        ]
        return (
            len(children) == 1
            and isinstance(children[0], Tag)
            and children[0].name in ("strong", "b")
        )

    processed: set[int] = set()
    for block in soup.find_all(["p", "div"]):
        if id(block) in processed or not _is_sole_bold(block):
            continue

        run: list[Tag] = [block]
        nxt = block.next_sibling
        while nxt is not None:
            if isinstance(nxt, NavigableString) and not nxt.strip():
                nxt = nxt.next_sibling
                continue
            if (
                isinstance(nxt, Tag)
                and nxt.name in ("p", "div")
                and _is_sole_bold(nxt)
            ):
                run.append(nxt)
                nxt = nxt.next_sibling
                continue
            break

        if len(run) >= _MIN_RUN:
            for b in run:
                processed.add(id(b))
                children = [
                    c
                    for c in b.children
                    if not (isinstance(c, NavigableString) and not c.strip())
                ]
                if isinstance(children[0], Tag):
                    children[0].unwrap()


def _merge_adjacent_inline(
    soup: BeautifulSoup,
    tag_names: tuple[str, ...] = ("strong", "b", "em", "i"),
) -> None:
    """Merge adjacent sibling inline-emphasis tags of the same name.

    `<strong>A</strong><strong>B</strong>` and
    `<strong>A</strong> <strong>B</strong>` (at most one whitespace-only text
    node between) are collapsed to a single `<strong>A B</strong>`. Fixes the
    `**A****B**` / `**A** **B**` output from markdownify at the source — the
    post-process pass is only a fallback safety net for WYSIWYG mixes of
    `<strong>` and `<b>` that fall outside this name-equality check.

    Runs to a fixed point so 3+ consecutive siblings collapse in one call.
    """
    for _ in range(MAX_EMPTY_PASSES):
        changed = False
        for tag in list(soup.find_all(tag_names)):
            if tag.parent is None:
                continue  # already merged into a previous sibling
            nxt = tag.next_sibling
            bridge: NavigableString | None = None
            if isinstance(nxt, NavigableString) and not nxt.strip():
                bridge = nxt
                nxt = nxt.next_sibling
            if not isinstance(nxt, Tag) or nxt.name != tag.name:
                continue
            if bridge is not None:
                tag.append(bridge.extract())
            for child in list(nxt.children):
                tag.append(child.extract())
            nxt.decompose()
            changed = True
        if not changed:
            break


# ── Main Pipeline ──────────────────────────────────────

def clean_html(raw_html: str, base_url: str) -> str | None:
    """
    Clean raw HTML for mobile rendering. 6-step pipeline:
    1. Junk element removal (+ 1.5 data URI image strip, 1.6 SmartEditor table unwrap)
    2. Semantic tag normalization (+ 2.5 underline em/i unwrap)
    3. URL absolute path conversion
    4. Tag allowlist + style property filtering via nh3
    5. Empty element cleanup
    6. Structural cleanup (empty span unwrap, div chain collapse, data URI re-strip,
       punctuation-only inline strip, sole-child bold unwrap, adjacent inline merge)
    """
    if not raw_html or raw_html.strip() == "":
        return None

    try:
        soup = BeautifulSoup(raw_html, "lxml")
        # Remove html/body wrapper that lxml adds
        body = soup.body
        if body:
            soup = BeautifulSoup(body.decode_contents(), "html.parser")

        # ── Step 1: Junk element removal ─────────────────
        for sel in REMOVE_SELECTORS:
            for el in soup.select(sel):
                el.decompose()

        # ── Step 1.5: Strip data URI images ─────────────
        for img in soup.select("img[src^='data:']"):
            img.decompose()

        # ── Step 1.6: Unwrap Naver SmartEditor layout tables ──
        # SmartEditor wraps content in deeply nested layout tables with
        # class `__se_tbl_ext`.  After nh3 strips classes they become
        # indistinguishable from data tables, so unwrap while the class
        # is still available.
        _unwrap_naver_smarteditor_tables(soup)

        # ── Step 1.7: Convert <pre> blocks to <p>+<br> ───
        # <pre> is not in ALLOWED_TAGS, so nh3 strips the wrapper and leaves
        # raw text with literal \n.  That text then leaks into markdown as
        # accidental list syntax ("1. ", "- ").  Converting before nh3
        # preserves line structure as block elements.
        _convert_pre_to_paragraphs(soup)

        # ── Step 2: Semantic tag normalization ────────────
        for el in soup.select("[style]"):
            if not isinstance(el, Tag):
                continue
            tag_name = el.name.lower() if el.name else ""
            if tag_name not in INLINE_ELEMENTS:
                continue

            style = el.get("style", "")
            if not isinstance(style, str):
                continue

            # font-weight: bold / bolder / 600+ → <strong>
            fw = _get_style_prop(style, "font-weight")
            if fw and _is_bold_weight(fw):
                strong = soup.new_tag("strong")
                for child in list(el.children):
                    strong.append(child.extract())
                el.append(strong)
                style = _remove_style_prop(style, "font-weight")

            # font-style: italic → <em>
            fs = _get_style_prop(style, "font-style")
            if fs and fs == "italic":
                em = soup.new_tag("em")
                for child in list(el.children):
                    em.append(child.extract())
                el.append(em)
                style = _remove_style_prop(style, "font-style")

            trimmed = style.rstrip("; ").strip()
            if trimmed:
                el["style"] = trimmed
            else:
                del el["style"]

        # ── Step 2.5: Unwrap <em>/<i> misused for underline ──
        # Some WYSIWYG editors use <em style="text-decoration: underline">
        # for underline rather than italic emphasis. Since underline has no
        # markdown equivalent, unwrap to plain text. Must run before nh3
        # while inline styles are still present.
        for em_tag in list(soup.find_all(["em", "i"])):
            em_style = em_tag.get("style", "")
            if not isinstance(em_style, str):
                continue
            td = _get_style_prop(em_style, "text-decoration")
            if td and "underline" in td.lower():
                em_tag.unwrap()

        # ── Step 3: URL absolute path conversion ─────────
        for img in soup.select("img[src]"):
            src = img.get("src")
            if src and isinstance(src, str):
                img["src"] = _resolve_url(src, base_url)

        for a in soup.select("a[href]"):
            href = a.get("href")
            if href and isinstance(href, str):
                a["href"] = _resolve_url(href, base_url)

        # ── Step 4: Tag allowlist + style filtering via nh3
        serialized = soup.decode_contents()
        sanitized = nh3.clean(
            serialized,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRIBUTES,
            url_schemes=ALLOWED_URL_SCHEMES,
            link_rel=None,
            filter_style_properties=ALLOWED_STYLE_PROPERTIES,
        )

        # ── Step 5: Empty element cleanup ────────────────
        clean_soup = BeautifulSoup(sanitized, "html.parser")

        for _ in range(MAX_EMPTY_PASSES):
            changed = False
            for tag in clean_soup.find_all(True):
                if not isinstance(tag, Tag):
                    continue
                if tag.name in REMOVABLE_EMPTY_TAGS and _is_effectively_empty(tag):
                    tag.decompose()
                    changed = True
            if not changed:
                break

        # ── Step 6: Structural cleanup ───────────────────
        # nh3 preserves allowlisted tags verbatim even when they carry no
        # semantic value after style/class stripping. These passes unwrap
        # empty span wrappers and collapse redundant div chains, and catch
        # data URI images that slipped past Step 1.5.
        _unwrap_empty_spans(clean_soup)
        _collapse_single_child_div_chains(clean_soup)
        _strip_data_uri_images(clean_soup)
        # Unwrap punctuation-only strongs first so their real-text siblings
        # become adjacent and eligible for the merge pass below.
        _strip_punctuation_only_inline(clean_soup)
        _strip_sole_child_bold(clean_soup)
        _merge_adjacent_inline(clean_soup)

        result = clean_soup.decode_contents()
        if not result or result.replace("\u00a0", "").strip() == "":
            return None

        return result

    except Exception as exc:
        logger.warning("cleanhtml_pipeline_failed", error=str(exc))
        return None


def normalize_content_urls(raw_html: str | None, base_url: str) -> str | None:
    """
    Resolve relative `src` and `href` attributes in raw notice HTML to
    absolute URLs, leaving everything else (tags, classes, inline styles,
    structure) untouched.

    Unlike `clean_html`, this is a non-destructive transform meant for the
    `content` field that consumers (mobile app, server transform) display
    directly. The mobile renderer cannot resolve `src="_attach/..."` against
    the page URL on its own (no DOM, no `<base>` tag), and SKKU's image
    server rejects raw paths anyway — so we have to bake absolute URLs into
    the stored HTML at crawl time.

    `cleanHtml` already does URL resolution as part of its pipeline; this
    helper does ONLY that step on the raw input.
    """
    if raw_html is None:
        return None
    if raw_html == "":
        return ""

    try:
        soup = BeautifulSoup(raw_html, "html.parser")

        for img in soup.select("img[src]"):
            src = img.get("src")
            if src and isinstance(src, str):
                img["src"] = _resolve_url(src, base_url)

        for a in soup.select("a[href]"):
            href = a.get("href")
            if href and isinstance(href, str):
                a["href"] = _resolve_url(href, base_url)

        return soup.decode_contents()
    except Exception as exc:
        logger.warning("normalize_content_urls_failed", error=str(exc))
        return raw_html
