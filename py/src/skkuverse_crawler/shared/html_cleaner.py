from __future__ import annotations

from urllib.parse import urljoin

import nh3
from bs4 import BeautifulSoup, Tag

from .logger import get_logger

logger = get_logger("html_cleaner")

# ── Constants ──────────────────────────────────────────

# Step 1: Selectors for junk elements to remove
REMOVE_SELECTORS = [
    "script", "style", "iframe", "form", "input", "button",
    "tfoot",
    ".board-view-title-wrap",
    ".board-view-file-wrap",
    ".board-view-nav",
    'a[href*="mode=list"]',
]

# Step 2: Only inline elements get font-weight→<strong> / font-style→<em>
INLINE_ELEMENTS = frozenset([
    "span", "a", "font", "b", "i", "u", "em", "strong", "mark",
])

# Step 4: nh3 configuration
ALLOWED_TAGS = {
    "p", "br", "div", "span", "h1", "h2", "h3", "h4",
    "strong", "b", "em", "i", "u", "mark",
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
    "p", "span", "div", "strong", "b", "em", "i", "u", "mark",
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


# ── Main Pipeline ──────────────────────────────────────

def clean_html(raw_html: str, base_url: str) -> str | None:
    """
    Clean raw HTML for mobile rendering. 5-step pipeline:
    1. Junk element removal
    2. Semantic tag normalization (inline elements only)
    3. URL absolute path conversion
    4. Tag allowlist + style property filtering via nh3
    5. Empty element cleanup
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

            # font-weight: bold / 700 → <strong>
            fw = _get_style_prop(style, "font-weight")
            if fw and fw in ("bold", "700"):
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
