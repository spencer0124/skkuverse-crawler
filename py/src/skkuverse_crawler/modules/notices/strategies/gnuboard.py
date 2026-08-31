from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlparse

from ....shared.fetcher import Fetcher
from ....shared.logger import get_logger
from ..models import NoticeDetail, NoticeListItem
from ..parser import load_html, extract_text, extract_attr
from ..types import DetailRef

logger = get_logger("gnuboard")


def normalize_date(date_str: str) -> str:
    """Normalize Gnuboard date formats.
    - "MM-DD" → "YYYY-MM-DD" (current or previous year)
    - "YY-MM-DD" → "20YY-MM-DD"
    - "MM.DD YYYY" → "YYYY-MM-DD" (saint's theme puts the year last)
    """
    if re.match(r"^\d{2}-\d{2}$", date_str):
        now = datetime.now()
        month = int(date_str.split("-")[0])
        year = now.year - 1 if month > now.month else now.year
        return f"{year}-{date_str}"
    if re.match(r"^\d{2}-\d{2}-\d{2}$", date_str):
        return f"20{date_str}"
    # Parsing this one is load-bearing, not cosmetic: an unrecognised format
    # falls through unchanged and page_below_floor then string-compares raw
    # theme text against an ISO floor, which disables the floor entirely.
    m = re.match(r"^(\d{2})\.(\d{2})\s+(\d{4})$", date_str)
    if m:
        return f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
    return date_str


def parse_article_no(href: str) -> int | None:
    """Article number from a Gnuboard link, query-string or rewrite form.

    ``wr_id=`` is tried first so existing boards keep their exact previous
    result; the path-tail branch only ever sees links that had no wr_id at
    all. Sites with mod_rewrite on (saint) render "/05_03/473?page=2" — and
    a strategy that returns None there drops every row of the page, leaving
    a source that fetches 200 OK and stores nothing (known-issues §12c).
    """
    m = re.search(r"wr_id=(\d+)", href) or re.search(r"/(\d+)(?:\?|$)", href)
    return int(m.group(1)) if m else None


class GnuboardStrategy:
    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    async def crawl_list(self, config: dict, page: int) -> list[NoticeListItem]:
        page_num = page + 1
        url = f"{config['baseUrl']}?{config['boardParam']}={config['boardName']}&page={page_num}"

        logger.info("fetching_gnuboard_list", url=url, page=page)
        html = await self.fetcher.fetch(url)
        soup = load_html(html)

        items: list[NoticeListItem] = []

        if config.get("skinType") == "table":
            self._parse_table_skin(soup, config, items)
        else:
            self._parse_list_skin(soup, config, items)

        logger.info("parsed_gnuboard_list", page=page, count=len(items))
        return items

    def _parse_table_skin(self, soup, config: dict, items: list[NoticeListItem]) -> None:
        selectors = config["selectors"]
        for tr in soup.select(selectors["listRow"]):
            try:
                tds = tr.select("td")
                if len(tds) < 2:
                    continue

                title_link = tr.select_one(selectors["titleLink"])
                title = extract_text(title_link).strip()
                if not title:
                    continue

                href = extract_attr(title_link, "href") or ""
                article_no = parse_article_no(href)
                if article_no is None:
                    continue

                author_sel = selectors.get("author")
                author = extract_text(tr.select_one(author_sel)) if author_sel else ""

                views_sel = selectors.get("views")
                views_text = extract_text(tr.select_one(views_sel)) if views_sel else "0"
                vm = re.search(r"(\d+)", views_text)
                views = int(vm.group(1)) if vm else 0

                date_raw = extract_text(tr.select_one(selectors["date"]))
                date = normalize_date(date_raw)

                items.append(NoticeListItem(
                    articleNo=article_no, title=title, category="",
                    author=author, date=date, views=views, detailPath=href,
                ))
            except Exception as exc:
                logger.warning("parse_gnuboard_table_failed", error=str(exc))

    def _parse_list_skin(self, soup, config: dict, items: list[NoticeListItem]) -> None:
        selectors = config["selectors"]
        for el in soup.select(selectors["listRow"]):
            try:
                link = el.select_one(selectors["titleLink"])
                href = extract_attr(link, "href") or ""
                if href.startswith("//"):
                    href = "https:" + href

                article_no = parse_article_no(href)
                if article_no is None:
                    continue

                # Title
                title_text_sel = selectors.get("titleText")
                if title_text_sel:
                    h2 = el.select_one(title_text_sel)
                    if h2:
                        cat_span = h2.select_one("span.category")
                        cat_text = cat_span.get_text(strip=True) if cat_span else ""
                        title = h2.get_text(strip=True).replace(cat_text, "").strip()
                    else:
                        title = extract_text(link)
                else:
                    title = extract_text(link)
                if not title:
                    continue

                author_sel = selectors.get("author")
                author = extract_text(el.select_one(author_sel)) if author_sel else ""
                date_raw = extract_text(el.select_one(selectors["date"]))
                date = normalize_date(date_raw)

                views_sel = selectors.get("views")
                views_text = extract_text(el.select_one(views_sel)) if views_sel else "0"
                vm = re.search(r"(\d+)", views_text)
                views = int(vm.group(1)) if vm else 0

                items.append(NoticeListItem(
                    articleNo=article_no, title=title, category="",
                    author=author, date=date, views=views, detailPath=href,
                ))
            except Exception as exc:
                logger.warning("parse_gnuboard_list_failed", error=str(exc))

    async def crawl_detail(self, ref: DetailRef, config: dict) -> NoticeDetail | None:
        if ref["detailPath"].startswith("http"):
            url = ref["detailPath"]
        elif ref["detailPath"].startswith("?"):
            url = f"{config['baseUrl']}{ref['detailPath']}"
        else:
            url = f"{config['baseUrl']}?{config['boardParam']}={config['boardName']}&wr_id={ref['articleNo']}"

        try:
            html = await self.fetcher.fetch(url)
            soup = load_html(html)
            selectors = config["selectors"]

            content_el = soup.select_one(selectors["detailContent"])
            content = content_el.decode_contents().strip() if content_el else ""
            content_text = content_el.get_text(strip=True) if content_el else ""

            attachments: list[dict[str, str]] = []
            parsed = urlparse(config["baseUrl"])
            origin = f"{parsed.scheme}://{parsed.netloc}"

            # Optional: a board whose downloads are gated behind a member
            # login (saint) omits the selector entirely, so that nothing is
            # stored promising a file the proxy can never fetch. Hard-indexing
            # here would raise into the except below and lose the *content*
            # too, turning an attachment decision into a dead source.
            attachment_sel = selectors.get("detailAttachment")
            for a in soup.select(attachment_sel) if attachment_sel else []:
                name = a.get_text(strip=True)
                file_href = extract_attr(a, "href") or ""
                if not name or not file_href:
                    continue
                if file_href.startswith("//"):
                    file_href = "https:" + file_href
                if file_href.startswith("/"):
                    file_href = f"{origin}{file_href}"
                elif not file_href.startswith("http"):
                    file_href = f"{origin}/{file_href}"
                attachments.append({"name": name, "url": file_href, "referer": url})

            return NoticeDetail(content=content, contentText=content_text, attachments=attachments)
        except Exception as exc:
            logger.error("gnuboard_detail_failed", articleNo=ref["articleNo"], error=str(exc))
            return None
