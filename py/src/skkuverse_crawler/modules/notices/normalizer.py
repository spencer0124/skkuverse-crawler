from __future__ import annotations

import re
from dataclasses import dataclass
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


@dataclass(frozen=True)
class ContentFields:
    """The five stored fields derived from one detail page's raw HTML.

    Field names are the STORED (camelCase) ones on purpose: both callers
    turn this into a Mongo ``$set``, and a snake_case dataclass here would
    mean two hand-written mappings that can drift apart — which is the
    exact failure this type exists to end.
    """

    content: str | None
    contentText: str | None
    cleanHtml: str | None
    cleanMarkdown: str | None
    contentHash: str | None

    def as_set(self) -> dict[str, str | None]:
        """The `$set` payload for a store that keeps these five together."""
        return {
            "content": self.content,
            "contentText": self.contentText,
            "cleanHtml": self.cleanHtml,
            "cleanMarkdown": self.cleanMarkdown,
            "contentHash": self.contentHash,
        }


def derive_content_fields(
    raw_html: str | None,
    base_url: str,
    *,
    fallback_text: str | None = None,
    image_dimensions: dict[str, tuple[int, int]] | None = None,
    article_no: int | None = None,
    source_id: str = "",
) -> ContentFields:
    """Derive every stored content field from one detail page's raw HTML.

    The single definition of what a notice's content fields mean. It exists
    because there was more than one: the Tier-2 update checker rebuilt
    ``content``/``cleanHtml``/``contentHash`` by hand and, over time, drifted
    from the crawl path three ways — no ``cleanMarkdown`` at all (the app's
    first-choice render source, so an edited notice showed its old body), a
    ``contentText`` taken straight from the strategy instead of extracted
    from the sanitized HTML (losing the block newlines added in 2026-04),
    and no size guard (so an oversized document was written where the crawl
    path stores nulls). Every one of those was silent.

    ``fallback_text`` is the strategy's own text, used only when nothing can
    be extracted from the sanitized HTML — the crawl path's precedence,
    preserved.
    """
    if not raw_html:
        return ContentFields(None, fallback_text or None, None, None, None)

    cleaned = clean_html(raw_html, base_url)
    # Resolve relative <img src> / <a href> in the raw content so the
    # mobile renderer doesn't have to.
    raw_content: str | None = normalize_content_urls(raw_html, base_url)

    if cleaned and image_dimensions:
        cleaned = _inject_image_dimensions(cleaned, image_dimensions)

    if cleaned and len(cleaned.encode()) > MAX_CONTENT_BYTES:
        logger.warning(
            "oversized_content_dropped",
            articleNo=article_no,
            dept=source_id,
            size=len(cleaned.encode()),
        )
        cleaned = None
        raw_content = None

    content_text = _text_from_clean_html(cleaned) if cleaned else None
    if content_text is None and fallback_text:
        content_text = fallback_text

    return ContentFields(
        content=raw_content,
        contentText=content_text,
        cleanHtml=cleaned,
        cleanMarkdown=html_to_markdown(cleaned),
        contentHash=compute_content_hash(cleaned),
    )


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

    # Build sourceUrl from detailPath
    if list_item.detailPath.startswith("http"):
        source_url = list_item.detailPath
    elif list_item.detailPath.startswith("?"):
        source_url = f"{base_url}{list_item.detailPath}"
    else:
        source_url = urljoin(base_url, list_item.detailPath)

    if content is not None:
        cleaned = content.clean_html
        raw_content = content.content
        content_text = content.text if content.clean_html else None
        clean_markdown = content.markdown
        content_hash = content.content_hash
    else:
        fields = derive_content_fields(
            detail.content if detail else None,
            base_url,
            fallback_text=detail.contentText if detail else None,
            image_dimensions=image_dimensions,
            article_no=list_item.articleNo,
            source_id=source_id,
        )
        cleaned = fields.cleanHtml
        raw_content = fields.content
        content_text = fields.contentText
        clean_markdown = fields.cleanMarkdown
        content_hash = fields.contentHash

    # The pipeline path derives content_text from its own stage, which does
    # not know the strategy's text; the fallback belongs to both paths.
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
