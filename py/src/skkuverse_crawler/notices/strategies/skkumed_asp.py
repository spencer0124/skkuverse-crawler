from __future__ import annotations

import re
from urllib.parse import urlparse

from ...shared.fetcher import Fetcher
from ...shared.logger import get_logger
from ..models import NoticeDetail, NoticeListItem
from ..parser import load_html, extract_text, extract_attr
from ..types import DetailRef

logger = get_logger("skkumed_asp")


class SkkumedAspStrategy:
    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    async def _fetch_euckr(self, url: str) -> str:
        buf = await self.fetcher.fetch_binary(url)
        return buf.decode("cp949", errors="replace")

    async def crawl_list(self, config: dict, page: int) -> list[NoticeListItem]:
        pg_num = page + 1
        extra = ""
        if config.get("extraParams"):
            extra = "&".join(f"{k}={v}" for k, v in config["extraParams"].items()) + "&"
        url = f"{config['baseUrl']}?{extra}{config['pagination']['param']}={pg_num}"

        logger.info("fetching_asp_list", url=url, page=page)
        html = await self._fetch_euckr(url)
        soup = load_html(html)

        items: list[NoticeListItem] = []
        selectors = config["selectors"]

        for el in soup.select(selectors["listItem"]):
            try:
                title_link = el.select_one(selectors["titleLink"])
                title = extract_text(title_link).lstrip("·").strip()
                href = extract_attr(title_link, "href") or ""

                m = re.search(r"number=(\d+)", href)
                if not m:
                    continue
                article_no = int(m.group(1))

                info_items = el.select(selectors["infoList"])
                info_texts = [li.get_text(strip=True) for li in info_items]

                author = info_texts[1] if len(info_texts) > 1 else ""
                date = info_texts[2] if len(info_texts) > 2 else ""
                views_text = info_texts[3] if len(info_texts) > 3 else "0"
                vm = re.search(r"(\d+)", views_text)
                views = int(vm.group(1)) if vm else 0

                items.append(NoticeListItem(
                    articleNo=article_no, title=title, category="",
                    author=author, date=date, views=views, detailPath=href,
                ))
            except Exception as exc:
                logger.warning("parse_asp_item_failed", error=str(exc))

        logger.info("parsed_asp_list", page=page, count=len(items))
        return items

    async def crawl_detail(self, ref: DetailRef, config: dict) -> NoticeDetail | None:
        if ref["detailPath"].startswith("http"):
            url = ref["detailPath"]
        else:
            parsed = urlparse(config["baseUrl"])
            origin = f"{parsed.scheme}://{parsed.netloc}"
            url = f"{origin}/{ref['detailPath'].lstrip('/')}"

        try:
            html = await self._fetch_euckr(url)
            soup = load_html(html)

            content_el = soup.select_one(config["selectors"]["detailContent"])
            if content_el:
                # Word-exported notices often embed <title>제목없음</title> and
                # other head-only tags inline next to <p> blocks. Strip them
                # before serialization so the stored `content` field stays
                # clean for downstream consumers even without clean_html.
                for tag in content_el.select("style, head, title, meta, link"):
                    tag.decompose()
                content = content_el.decode_contents().strip()
                content_text = content_el.get_text(strip=True)
            else:
                content = ""
                content_text = ""

            attachments: list[dict[str, str]] = []
            parsed_base = urlparse(config["baseUrl"])
            origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
            for a in soup.select(config["selectors"]["attachmentList"]):
                name = extract_text(a)
                file_url = extract_attr(a, "href")
                if name and file_url and file_url != "#":
                    full_url = file_url if file_url.startswith("http") else f"{origin}/{file_url.lstrip('/')}"
                    attachments.append({"name": name, "url": full_url})

            return NoticeDetail(content=content, contentText=content_text, attachments=attachments)
        except Exception as exc:
            logger.error("asp_detail_failed", articleNo=ref["articleNo"], error=str(exc))
            return None
