from __future__ import annotations

from datetime import datetime, timezone

from bs4 import BeautifulSoup, Tag

from ..shared.html_cleaner import clean_html, normalize_content_urls
from ..shared.logger import get_logger
from .hashing import compute_content_hash
from .models import Notice, NoticeDetail, NoticeListItem

logger = get_logger("normalizer")

MAX_CONTENT_BYTES = 5 * 1024 * 1024  # 5MB


def _text_from_clean_html(html: str) -> str:
    """cleanHtml에서 plain text 추출. 테이블 셀 사이에 공백 삽입."""
    soup = BeautifulSoup(html, "html.parser")
    for el in soup.find_all(["td", "th"]):
        if isinstance(el, Tag):
            el.append(" ")
    return soup.get_text(separator=" ", strip=True)


def build_notice(
    list_item: NoticeListItem,
    detail: NoticeDetail | None,
    *,
    department: str,
    source_dept_id: str,
    base_url: str,
) -> Notice:
    # Build sourceUrl from detailPath
    if list_item.detailPath.startswith("http"):
        source_url = list_item.detailPath
    elif list_item.detailPath.startswith("?"):
        source_url = f"{base_url}{list_item.detailPath}"
    else:
        source_url = f"{base_url}?mode=view&articleNo={list_item.articleNo}"

    cleaned = clean_html(detail.content, base_url) if detail and detail.content else None
    # Resolve relative <img src> / <a href> in the raw content so the
    # mobile renderer doesn't have to.
    raw_content = (
        normalize_content_urls(detail.content, base_url) if detail and detail.content else None
    )

    if cleaned and len(cleaned.encode()) > MAX_CONTENT_BYTES:
        logger.warning(
            "oversized_content_dropped",
            articleNo=list_item.articleNo,
            dept=source_dept_id,
            size=len(cleaned.encode()),
        )
        cleaned = None
        raw_content = None

    if cleaned:
        content_text = _text_from_clean_html(cleaned)
    elif detail and detail.contentText:
        content_text = detail.contentText
    else:
        content_text = None

    return Notice(
        articleNo=list_item.articleNo,
        title=list_item.title,
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
        sourceDeptId=source_dept_id,
        crawledAt=datetime.now(timezone.utc),
        contentHash=compute_content_hash(cleaned),
    )
