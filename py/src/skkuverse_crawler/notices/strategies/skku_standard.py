from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse, urlencode, parse_qs, urlunparse

from ...shared.fetcher import Fetcher
from ...shared.logger import get_logger
from ..models import NoticeDetail, NoticeListItem
from ..parser import load_html, extract_text, extract_attr
from ..types import DetailRef

logger = get_logger("skku_standard")


class SkkuStandardStrategy:
    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    async def crawl_list(self, config: dict, page: int) -> list[NoticeListItem]:
        pagination = config["pagination"]
        offset = page * pagination["limit"]
        extra = ""
        if config.get("extraParams"):
            extra = "&".join(f"{k}={v}" for k, v in config["extraParams"].items()) + "&"
        url = f"{config['baseUrl']}?{extra}mode=list&articleLimit={pagination['limit']}&{pagination['param']}={offset}"

        logger.info("fetching_list_page", url=url, page=page)
        html = await self.fetcher.fetch(url)
        soup = load_html(html)

        items: list[NoticeListItem] = []
        selectors = config["selectors"]

        for el in soup.select(selectors["listItem"]):
            try:
                # Category
                cat_el = el.select_one(selectors["category"])
                category_raw = extract_text(cat_el)
                category = category_raw.strip("[]")

                # Title + link
                title_link = el.select_one(selectors["titleLink"])
                title = extract_text(title_link).strip()
                href = extract_attr(title_link, "href") or ""

                # Extract articleNo
                m = re.search(r"articleNo=(\d+)", href) or re.search(r"itemId=(\d+)", href)
                if not m:
                    logger.warning("no_article_no", href=href, title=title)
                    continue
                article_no = int(m.group(1))

                # Info list
                info_items = el.select(selectors["infoList"])
                info_texts = [li.get_text(strip=True) for li in info_items]

                if config.get("infoParser") == "labeled":
                    info_map: dict[str, str] = {}
                    for text in info_texts:
                        lm = re.match(r"^(.+?)\s*:\s*(.+)$", text)
                        if lm:
                            info_map[lm.group(1).strip().upper()] = lm.group(2).strip()
                    date = info_map.get("POSTED DATE", "")
                    author = info_map.get("WRITER", "")
                    hits_text = info_map.get("HIT", "0")
                    hits_m = re.search(r"(\d+)", hits_text)
                    views = int(hits_m.group(1)) if hits_m else 0
                else:
                    author = info_texts[1] if len(info_texts) > 1 else ""
                    date = info_texts[2] if len(info_texts) > 2 else ""
                    views_text = info_texts[3] if len(info_texts) > 3 else "0"
                    views_m = re.search(r"(\d+)", views_text)
                    views = int(views_m.group(1)) if views_m else 0

                items.append(NoticeListItem(
                    articleNo=article_no,
                    title=title,
                    category=category,
                    author=author,
                    date=date,
                    views=views,
                    detailPath=href,
                ))
            except Exception as exc:
                logger.warning("parse_list_item_failed", error=str(exc))

        logger.info("parsed_list_page", page=page, count=len(items))
        return items

    async def crawl_detail(self, ref: DetailRef, config: dict) -> NoticeDetail | None:
        # Build detail URL
        if ref["detailPath"].startswith("http"):
            url = ref["detailPath"]
        elif ref["detailPath"].startswith("?"):
            if config.get("extraParams"):
                params = dict(parse_qs(ref["detailPath"][1:], keep_blank_values=True))
                flat_params = {k: v[0] if isinstance(v, list) else v for k, v in params.items()}
                for k, v in config["extraParams"].items():
                    if k not in flat_params:
                        flat_params[k] = v
                url = f"{config['baseUrl']}?{urlencode(flat_params)}"
            else:
                url = f"{config['baseUrl']}{ref['detailPath']}"
        else:
            extra = ""
            if config.get("extraParams"):
                extra = "&".join(f"{k}={v}" for k, v in config["extraParams"].items()) + "&"
            url = f"{config['baseUrl']}?{extra}mode=view&articleNo={ref['articleNo']}&article.offset=0&articleLimit=10"

        try:
            html = await self.fetcher.fetch(url)
            soup = load_html(html)
            selectors = config["selectors"]

            # Content with fallbacks
            content_el = soup.select_one(selectors["detailContent"])
            if not content_el:
                for fallback in ["div.board-view-content-wrap", "div.fr-view"]:
                    content_el = soup.select_one(fallback)
                    if content_el:
                        break

            content = content_el.decode_contents().strip() if content_el else ""
            content_text = content_el.get_text(strip=True) if content_el else ""

            # Attachments
            attachments: list[dict[str, str]] = []
            for a in soup.select(selectors["attachmentList"]):
                name = extract_text(a)

                if config.get("attachmentParser") == "onclick":
                    onclick = extract_attr(a, "onclick") or ""
                    om = re.search(r"location\.href='([^']+)'", onclick)
                    file_url = om.group(1).replace("&amp;", "&") if om else None
                else:
                    file_url = extract_attr(a, "href")

                if name and file_url and file_url != "#":
                    if file_url.startswith("http"):
                        full_url = file_url
                    elif file_url.startswith("?"):
                        full_url = f"{config['baseUrl']}{file_url}"
                    else:
                        parsed = urlparse(config["baseUrl"])
                        origin = f"{parsed.scheme}://{parsed.netloc}"
                        full_url = f"{origin}{'/' if not file_url.startswith('/') else ''}{file_url}"
                    attachments.append({"name": name, "url": full_url})

            return NoticeDetail(content=content, contentText=content_text, attachments=attachments)
        except Exception as exc:
            logger.error("detail_fetch_failed", articleNo=ref["articleNo"], error=str(exc))
            return None
