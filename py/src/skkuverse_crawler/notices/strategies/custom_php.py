from __future__ import annotations

import re
from urllib.parse import quote

from ...shared.fetcher import Fetcher
from ...shared.logger import get_logger
from ..models import NoticeDetail, NoticeListItem
from ..parser import load_html, extract_text
from ..types import DetailRef

logger = get_logger("custom_php")


class CustomPhpStrategy:
    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    async def crawl_list(self, config: dict, page: int) -> list[NoticeListItem]:
        pg_num = page + 1
        board_params = "&".join(
            f"{k}={quote(v)}" for k, v in config["boardParams"].items()
        )
        url = f"{config['baseUrl']}?{board_params}&pg={pg_num}&page=list"

        logger.info("fetching_custom_php_list", url=url, page=page)
        html = await self.fetcher.fetch(url)
        soup = load_html(html)

        items: list[NoticeListItem] = []
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

                href = (title_link.get("href", "") if title_link else "") or ""
                if isinstance(href, list):
                    href = href[0]

                m = re.search(r"idx=(\d+)", href)
                if not m:
                    continue
                article_no = int(m.group(1))

                category = tr.select_one(selectors["category"])
                category_text = extract_text(category)

                views_el = tr.select_one(selectors["views"])
                views_text = extract_text(views_el)
                vm = re.search(r"(\d+)", views_text)
                views = int(vm.group(1)) if vm else 0

                date_el = tr.select_one(selectors["date"])
                date = extract_text(date_el)

                items.append(NoticeListItem(
                    articleNo=article_no, title=title, category=category_text,
                    author="", date=date, views=views, detailPath=href,
                ))
            except Exception as exc:
                logger.warning("parse_custom_php_failed", error=str(exc))

        logger.info("parsed_custom_php_list", page=page, count=len(items))
        return items

    async def crawl_detail(self, ref: DetailRef, config: dict) -> NoticeDetail | None:
        if ref["detailPath"].startswith("http"):
            url = ref["detailPath"]
        elif ref["detailPath"].startswith("?"):
            url = f"{config['baseUrl']}{ref['detailPath']}"
        else:
            board_params = "&".join(
                f"{k}={quote(v)}" for k, v in config["boardParams"].items()
            )
            url = f"{config['baseUrl']}?page=view&idx={ref['articleNo']}&{board_params}"

        try:
            html = await self.fetcher.fetch(url)
            soup = load_html(html)

            content_el = soup.select_one(config["selectors"]["detailContent"])
            content = content_el.decode_contents().strip() if content_el else ""
            content_text = content_el.get_text(strip=True) if content_el else ""

            return NoticeDetail(content=content, contentText=content_text, attachments=[])
        except Exception as exc:
            logger.error("custom_php_detail_failed", articleNo=ref["articleNo"], error=str(exc))
            return None
