from __future__ import annotations

import re
from urllib.parse import urlparse

from ...shared.fetcher import Fetcher
from ...shared.logger import get_logger
from ..models import NoticeDetail, NoticeListItem
from ..parser import load_html, extract_text, extract_attr
from ..types import DetailRef

logger = get_logger("jsp_dorm")


class JspDormStrategy:
    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    async def crawl_list(self, config: dict, page: int) -> list[NoticeListItem]:
        pagination = config["pagination"]
        offset = page * pagination["limit"]
        url = f"{config['baseUrl']}?mode=list&board_no={config['boardNo']}&{pagination['param']}={offset}"

        logger.info("fetching_jsp_list", url=url, page=page)
        html = await self.fetcher.fetch(url)
        soup = load_html(html)

        items: list[NoticeListItem] = []
        selectors = config["selectors"]
        pinned_selector = selectors["pinnedRow"]

        for tr in soup.select(selectors["listRow"]):
            try:
                # Skip pinned on page > 0
                is_pinned = tr.select_one(pinned_selector.split(" ")[-1]) is not None if pinned_selector else False
                # More robust: check if tr matches the pinned selector pattern
                style_val = tr.get("style", "")
                if isinstance(style_val, list):
                    style = " ".join(style_val)
                else:
                    style = style_val or ""
                is_pinned = "background:#f4f4f4" in style.replace(" ", "")
                if is_pinned and page > 0:
                    continue

                tds = tr.select("td")
                if len(tds) < 6:
                    continue

                category = tds[1].get_text(strip=True)
                title_link = tds[2].select_one("a")
                title = extract_text(title_link).strip()
                href = extract_attr(title_link, "href") or ""
                date = tds[4].get_text(strip=True)
                views = int(tds[5].get_text(strip=True) or "0") if tds[5].get_text(strip=True).isdigit() else 0

                m = re.search(r"article_no=(\d+)", href)
                if not m:
                    continue

                items.append(NoticeListItem(
                    articleNo=int(m.group(1)), title=title, category=category,
                    author="", date=date, views=views, detailPath=href,
                ))
            except Exception as exc:
                logger.warning("parse_jsp_item_failed", error=str(exc))

        logger.info("parsed_jsp_list", page=page, count=len(items))
        return items

    async def crawl_detail(self, ref: DetailRef, config: dict) -> NoticeDetail | None:
        if ref["detailPath"].startswith("http"):
            url = ref["detailPath"]
        elif ref["detailPath"].startswith("?"):
            url = f"{config['baseUrl']}{ref['detailPath']}"
        else:
            url = f"{config['baseUrl']}?mode=view&article_no={ref['articleNo']}&board_no={config['boardNo']}"

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
            for a in soup.select(selectors["attachmentLink"]):
                # Remove img children to avoid alt text in name
                for img in a.select("img"):
                    img.decompose()
                name = a.get_text(strip=True)
                file_href = extract_attr(a, "href") or ""
                if name and file_href:
                    full_url = file_href if file_href.startswith("http") else f"{origin}{'/' if not file_href.startswith('/') else ''}{file_href}"
                    attachments.append({"name": name, "url": full_url})

            return NoticeDetail(content=content, contentText=content_text, attachments=attachments)
        except Exception as exc:
            logger.error("jsp_detail_failed", articleNo=ref["articleNo"], error=str(exc))
            return None
