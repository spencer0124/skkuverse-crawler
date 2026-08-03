from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ...core.pipeline import ContentDoc
from ...shared.html_cleaner import clean_html, normalize_content_urls
from ...shared.html_to_markdown import html_to_markdown
from ...shared.logger import get_logger
from .hashing import compute_content_hash
from .models import Notice, NoticeDetail, NoticeListItem

logger = get_logger("normalizer")

MAX_CONTENT_BYTES = 5 * 1024 * 1024  # 5MB

_MULTI_SPACE_RE = re.compile(r"[ \t]+")
_LEADING_WS_RE = re.compile(r"\n[ \t]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_BLOCK_ELEMENTS = ("tr", "p", "div", "br", "h1", "h2", "h3", "h4", "li")


def _text_from_clean_html(html: str) -> str:
    """cleanHtml에서 plain text 추출.

    - ``<td>``/``<th>`` 뒤에는 공백을 넣어 셀 사이 구분을 유지한다.
    - ``<tr>``, ``<p>``, ``<div>``, ``<h1>~<h4>``, ``<li>``, ``<br>`` 뒤에는
      개행을 넣어 블록 경계를 보존한다.
    - 단, 테이블 셀 내부의 ``<br>`` 은 셀 구분과 충돌하지 않도록 공백으로
      대체한다 (한 셀의 두 줄 짜리 내용이 다음 셀과 헷갈리게 붙는 것을 방지).
    """
    soup = BeautifulSoup(html, "html.parser")
    # 셀 뒤 공백 (기존 동작)
    for el in soup.find_all(["td", "th"]):
        if isinstance(el, Tag):
            el.append(" ")
    # 블록 경계 개행
    for el in soup.find_all(list(_BLOCK_ELEMENTS)):
        if not isinstance(el, Tag):
            continue
        if el.name == "br" and el.find_parent(["td", "th"]):
            # 셀 내부 br은 공백으로 (셀 구분과 섞이면 안 됨)
            el.replace_with(" ")
            continue
        el.append("\n")
    text = soup.get_text()
    # 공백/개행 정규화
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = _LEADING_WS_RE.sub("\n", text)
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()


def _inject_image_dimensions(
    html: str,
    dimensions: dict[str, tuple[int, int]],
) -> str:
    """Inject width/height attributes into ``<img>`` tags from detected dims."""
    soup = BeautifulSoup(html, "html.parser")
    changed = False
    for img in soup.find_all("img"):
        if not isinstance(img, Tag):
            continue
        src = img.get("src")
        if not isinstance(src, str) or src not in dimensions:
            continue
        # Don't overwrite existing dimensions from source HTML
        if img.get("width") or img.get("height"):
            continue
        w, h = dimensions[src]
        img["width"] = str(w)
        img["height"] = str(h)
        changed = True
    return str(soup) if changed else html


def source_url_for(base_url: str, detail_path: str) -> str:
    """The notice's own URL, from the list row's detailPath.

    Three shapes because the sources use three: an absolute URL, a bare
    query string to append, or a relative path to resolve. Shared rather
    than inlined because it is also the Referer the image probe sends, and
    the two used to be built differently — the probe concatenated where
    this joins, producing `…/community_notice.aspcommunity_notice_w.asp?…`
    for the one source whose detailPath is a sibling filename.
    """
    if detail_path.startswith("http"):
        return detail_path
    if detail_path.startswith("?"):
        return f"{base_url}{detail_path}"
    return urljoin(base_url, detail_path)


# `(?:\\.|[^\]\\])*` and not `[^\]]*`: the alt text is markdown-escaped, and
# SKKU titles are overwhelmingly of the form "[학사팀] 제목", which becomes
# `\[학사팀\]`. A class that cannot cross an escaped bracket stops at the
# first `\]`, and a hint that is not read cannot be re-injected — so the
# regenerated markdown loses it for good. Measured on production: 49
# documents whose last surviving measurement this would have destroyed.
_MD_DIMENSION_HINT = re.compile(r"!\[\{(\d+)x(\d+)\}(?:\\.|[^\]\\])*\]\(([^)]+)\)")


def dimensions_from_markdown(markdown: str | None) -> dict[str, tuple[int, int]]:
    """Read image dimensions back out of a stored ``cleanMarkdown``.

    The app's ``{WxH}`` hint is the only place the measurements survived a
    Tier-2 write: that path rewrote ``cleanHtml`` without them but never
    touched the markdown. So for repairing documents damaged before the
    Tier-2 fix, this is the measurement — already in the database, no
    re-crawl and no image fetch needed.

    Only the ``{WxH}`` form is read. ``{w800}``/``{h600}`` mean the source
    HTML carried one dimension and not the other, and half a dimension
    cannot be injected back (``_inject_image_dimensions`` writes both or
    neither, and the app's regex needs both).
    """
    if not markdown:
        return {}
    return {
        url: (int(width), int(height))
        for width, height, url in _MD_DIMENSION_HINT.findall(markdown)
    }


def dimensions_from_html(html: str | None) -> dict[str, tuple[int, int]]:
    """Read back the width/height already injected into an ``<img>``.

    The inverse of ``_inject_image_dimensions``, and it exists for one
    reason: the image probe is a live third-party request, so "no
    dimensions" can mean "this image has none" or "that host was slow just
    now". Seeding a derivation with what is already stored keeps a
    transient failure from silently dropping the app's size hint — and,
    because the hash is taken from this HTML, from inventing a content
    change out of someone else's downtime.
    """
    if not html:
        return {}
    dimensions: dict[str, tuple[int, int]] = {}
    for img in BeautifulSoup(html, "html.parser").find_all("img"):
        if not isinstance(img, Tag):
            continue
        src, width, height = img.get("src"), img.get("width"), img.get("height")
        if not isinstance(src, str) or not isinstance(width, str) or not isinstance(height, str):
            continue
        try:
            dimensions[src] = (int(width), int(height))
        except ValueError:
            continue
    return dimensions


def build_notice(
    list_item: NoticeListItem,
    detail: NoticeDetail | None,
    *,
    department: str,
    source_id: str,
    base_url: str,
    image_dimensions: dict[str, tuple[int, int]] | None = None,
    content: ContentDoc | None = None,
) -> Notice:
    """Assemble a Notice from a list row + detail page.

    ``content`` is the pipeline product (modules/notices/stages.py); the
    crawl path passes it, so the content slots arrive already derived.
    Without it this falls back to deriving them inline — the two paths are
    pinned equal by tests/notices/test_stages.py. The inline path keeps
    direct callers (fixtures, quality tests) free of pipeline setup; it
    retires when the last one moves (PR 9 계열).

    ``image_dimensions`` belongs to the inline path only: with a pipeline
    doc, injection already happened (InjectImageDimensions) and honoring
    it here would inject twice. Passing both is a caller bug, not a
    precedence question, so it raises rather than silently dropping one.
    """
    if content is not None and image_dimensions is not None:
        raise ValueError(
            "build_notice: pass image_dimensions or content, not both — "
            "a ContentDoc already carries injected dimensions"
        )

    source_url = source_url_for(base_url, list_item.detailPath)

    if content is not None:
        cleaned = content.clean_html
        raw_content = content.content
        content_text = content.text if content.clean_html else None
        clean_markdown = content.markdown
        content_hash = content.content_hash
    else:
        cleaned = clean_html(detail.content, base_url) if detail and detail.content else None
        # Resolve relative <img src> / <a href> in the raw content so the
        # mobile renderer doesn't have to.
        raw_content = (
            normalize_content_urls(detail.content, base_url) if detail and detail.content else None
        )

        if cleaned and image_dimensions:
            cleaned = _inject_image_dimensions(cleaned, image_dimensions)

        if cleaned and len(cleaned.encode()) > MAX_CONTENT_BYTES:
            logger.warning(
                "oversized_content_dropped",
                articleNo=list_item.articleNo,
                dept=source_id,
                size=len(cleaned.encode()),
            )
            cleaned = None
            raw_content = None

        content_text = _text_from_clean_html(cleaned) if cleaned else None
        clean_markdown = html_to_markdown(cleaned)
        content_hash = compute_content_hash(cleaned)

    if content_text is None and detail and detail.contentText:
        content_text = detail.contentText

    # Prefer full title from detail page over potentially truncated list title
    title = list_item.title
    if detail and detail.title:
        title = detail.title

    return Notice(
        articleNo=list_item.articleNo,
        title=title,
        category=list_item.category,
        author=list_item.author,
        department=department,
        date=list_item.date,
        views=list_item.views,
        content=raw_content,
        contentText=content_text,
        cleanHtml=cleaned,
        attachments=detail.attachments if detail else [],
        sourceUrl=source_url,
        detailPath=list_item.detailPath,
        sourceId=source_id,
        cleanMarkdown=clean_markdown,
        crawledAt=datetime.now(timezone.utc),
        contentHash=content_hash,
    )
