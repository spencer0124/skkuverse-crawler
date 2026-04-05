from __future__ import annotations

import re
from urllib.parse import urlparse

from ...shared.fetcher import Fetcher
from ...shared.logger import get_logger
from ..models import NoticeDetail, NoticeListItem
from ..parser import load_html, extract_text, extract_attr
from ..types import DetailRef

logger = get_logger("gnuboard_custom")


def clean_hwp_artifacts(html: str) -> str:
    cleaned = re.sub(r"<!--\[data-hwpjson\][\s\S]*?\[data-hwpjson\]-->", "", html)
    cleaned = re.sub(r'\s*data-hwpjson="[^"]*"', "", cleaned)
    return cleaned


class GnuboardCustomStrategy:
    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    async def crawl_list(self, config: dict, page: int) -> list[NoticeListItem]:
        page_num = page + 1
        url = f"{config['baseUrl']}?{config['boardParam']}={config['boardName']}&page={page_num}"

        logger.info("fetching_gnuboard_custom_list", url=url, page=page)
        html = await self.fetcher.fetch(url)
        soup = load_html(html)

        items: list[NoticeListItem] = []
        selectors = config["selectors"]

        for tr in soup.select(selectors["listRow"]):
            try:
                tds = tr.select("td")
                if len(tds) < 2:
                    continue

                # Skip pinned on page > 0
                if page > 0 and tr.select_one('img[src*="btn_notice"]'):
                    continue

                title_link = tr.select_one(selectors["titleLink"])
                title = extract_text(title_link).strip()
                if not title:
                    continue

                href = extract_attr(title_link, "href") or ""
                m = re.search(r"num=(\d+)", href)
                if not m:
                    continue
                article_no = int(m.group(1))

                date = extract_text(tr.select_one(selectors["date"]))

                meta_text = extract_text(tr.select_one(selectors["meta"]))
                parts = [s.strip() for s in meta_text.split("|")]
                author = parts[0] if parts else ""
                vm = re.search(r"조회수\s*:\s*(\d+)", meta_text)
                views = int(vm.group(1)) if vm else 0

                items.append(NoticeListItem(
                    articleNo=article_no, title=title, category="",
                    author=author, date=date, views=views, detailPath=href,
                ))
            except Exception as exc:
                logger.warning("parse_gnuboard_custom_failed", error=str(exc))

        logger.info("parsed_gnuboard_custom_list", page=page, count=len(items))
        return items

    async def crawl_detail(self, ref: DetailRef, config: dict) -> NoticeDetail | None:
        if ref["detailPath"].startswith("http"):
            url = ref["detailPath"]
        elif ref["detailPath"].startswith("?"):
            url = f"{config['baseUrl']}{ref['detailPath']}"
        else:
            url = f"{config['baseUrl']}?{config['boardParam']}={config['boardName']}&mode={config['detailMode']}&num={ref['articleNo']}"

        try:
            html = await self.fetcher.fetch(url)
            soup = load_html(html)
            selectors = config["selectors"]

            content_el = soup.select_one(selectors["detailContent"])
            raw_html = content_el.decode_contents().strip() if content_el else ""
            content = clean_hwp_artifacts(raw_html)
            content_soup = load_html(content)
            content_text = content_soup.get_text(strip=True)

            attachments: list[dict[str, str]] = []
            parsed = urlparse(config["baseUrl"])
            origin = f"{parsed.scheme}://{parsed.netloc}"

            for a in soup.select(selectors["detailAttachment"]):
                name = a.get_text(strip=True)
                file_href = extract_attr(a, "href") or ""
                if not name or not file_href:
                    continue
                if file_href.startswith("/"):
                    file_href = f"{origin}{file_href}"
                elif not file_href.startswith("http"):
                    file_href = f"{origin}/{file_href}"
                attachments.append({"name": name, "url": file_href})

            return NoticeDetail(content=content, contentText=content_text, attachments=attachments)
        except Exception as exc:
            logger.error("gnuboard_custom_detail_failed", articleNo=ref["articleNo"], error=str(exc))
            return None
