from __future__ import annotations

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup, Tag

from ..shared.html_cleaner import clean_html, normalize_content_urls
from ..shared.html_to_markdown import html_to_markdown
from ..shared.logger import get_logger
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

    clean_markdown = html_to_markdown(cleaned)

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
        cleanMarkdown=clean_markdown,
        crawledAt=datetime.now(timezone.utc),
        contentHash=compute_content_hash(cleaned),
    )
