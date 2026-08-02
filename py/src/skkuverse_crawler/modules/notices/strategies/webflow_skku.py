from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin, urlparse

from ....shared.fetcher import Fetcher
from ....shared.logger import get_logger
from ..models import NoticeDetail, NoticeListItem
from ..parser import extract_attr, extract_text, load_html
from ..types import DetailRef

logger = get_logger("webflow_skku")

_DATE_RE = re.compile(r"(\d{2,4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?")
_PAGE_TOKEN_RE = re.compile(r"[?&]([a-f0-9]{6,12}_page)=", re.IGNORECASE)
_ATTACH_EXT_RE = re.compile(
    r"\.(pdf|hwp|hwpx|docx?|xlsx?|pptx?|zip|txt|csv)(?:\?|$)",
    re.IGNORECASE,
)


def slug_to_article_no(slug_or_path: str) -> int:
    # 31-bit positive int → PyMongo stores BSON Int32 (NOT Long). Int32 is
    # serialized by the API as a plain JSON number; a Long (>2^31) leaks as
    # {high,low,unsigned} and the app coerces it to 0 → broken detail links.
    # Birthday-collision risk ~10^-4 at k=1000; the (articleNo, sourceId) unique
    # index turns a collision into a dropped (logged) upsert, not corruption.
    digest = hashlib.blake2b(slug_or_path.encode(), digest_size=4).digest()
    return int.from_bytes(digest, "big") & 0x7FFFFFFF


def _normalize_date(text: str) -> str:
    m = _DATE_RE.search(text or "")
    if not m:
        return ""
    y, mo, d = m.groups()
    year = int(y)
    if year < 100:
        # Source occasionally uses 2-digit year format like "24.09.19." — treat
        # as 20XX. Will need revisiting in year 2100 (not before).
        year += 2000
    return f"{year:04d}-{int(mo):02d}-{int(d):02d}"


def _origin(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


class WebflowSkkuStrategy:
    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher
        # Cache the pagination token discovered per baseUrl (handles republished sites)
        self._discovered_page_param: dict[str, str] = {}

    async def crawl_list(self, config: dict, page: int) -> list[NoticeListItem]:
        base_url = config["baseUrl"]
        selectors = config["selectors"]
        configured_token = config.get("pageParam", "")
        cached_token = self._discovered_page_param.get(base_url)
        token = cached_token or configured_token

        if page == 0:
            url = base_url
        else:
            if not token:
                logger.error("no_page_param_available", baseUrl=base_url, page=page)
                return []
            url = f"{base_url}?{token}={page + 1}"

        logger.info("fetching_list_page", url=url, page=page)
        html = await self.fetcher.fetch(url)
        soup = load_html(html)

        if page == 0:
            next_link = soup.select_one(selectors["paginationNext"])
            next_href = extract_attr(next_link, "href") if next_link else None
            if next_href:
                m = _PAGE_TOKEN_RE.search(next_href)
                if m:
                    discovered = m.group(1)
                    if configured_token and discovered != configured_token:
                        logger.warning(
                            "page_param_mismatch",
                            configured=configured_token,
                            discovered=discovered,
                            baseUrl=base_url,
                        )
                    self._discovered_page_param[base_url] = discovered

        items: list[NoticeListItem] = []
        origin = _origin(base_url)

        for el in soup.select(selectors["listItem"]):
            try:
                link = el.select_one(selectors["listLink"])
                href = extract_attr(link, "href") if link else None
                if not href:
                    continue  # hidden Webflow template row

                if href.startswith("http"):
                    full_url = href
                else:
                    full_url = urljoin(origin + "/", href.lstrip("/"))

                slug = href.rstrip("/").rsplit("/", 1)[-1] or href
                article_no = slug_to_article_no(slug)

                row = el.select_one(selectors["listRow"])
                if row is None:
                    logger.warning("no_row_container", href=href)
                    continue

                title_el = row.select_one(selectors["titleCell"])
                title = extract_text(title_el).strip()

                regular = [c.get_text(strip=True) for c in row.select(selectors["regularCell"])]
                # regular = [number, category, author, date]
                category = regular[1] if len(regular) > 1 else ""
                author = regular[2] if len(regular) > 2 else ""
                date = _normalize_date(regular[3] if len(regular) > 3 else "")

                if not title:
                    logger.warning("empty_title", href=href)
                    continue

                items.append(
                    NoticeListItem(
                        articleNo=article_no,
                        title=title,
                        category=category,
                        author=author,
                        date=date,
                        views=0,
                        detailPath=full_url,
                    )
                )
            except Exception as exc:
                logger.warning("parse_list_item_failed", error=str(exc))

        logger.info("parsed_list_page", page=page, count=len(items))
        return items

    async def crawl_detail(self, ref: DetailRef, config: dict) -> NoticeDetail | None:
        detail_path = ref["detailPath"]
        if detail_path.startswith("http"):
            url = detail_path
        else:
            url = urljoin(_origin(config["baseUrl"]) + "/", detail_path.lstrip("/"))

        try:
            html = await self.fetcher.fetch(url)
            soup = load_html(html)
            selectors = config["selectors"]

            title_el = soup.select_one(selectors["detailTitle"])
            detail_title = extract_text(title_el).strip() or None

            content_el = soup.select_one(selectors["detailContent"])
            content = content_el.decode_contents().strip() if content_el else ""
            content_text = (
                content_el.get_text(separator=" ", strip=True) if content_el else ""
            )

            attachments: list[dict[str, str]] = []
            if content_el is not None:
                page_origin = _origin(url)
                for a in content_el.select("a[href]"):
                    href = extract_attr(a, "href") or ""
                    if not _ATTACH_EXT_RE.search(href):
                        continue
                    name = extract_text(a) or href.rsplit("/", 1)[-1]
                    if href.startswith("http"):
                        full_url = href
                    elif href.startswith("//"):
                        full_url = f"https:{href}"
                    else:
                        full_url = urljoin(page_origin + "/", href.lstrip("/"))
                    attachments.append({"name": name, "url": full_url})

            return NoticeDetail(
                content=content,
                contentText=content_text,
                attachments=attachments,
                title=detail_title,
            )
        except Exception as exc:
            logger.error("detail_fetch_failed", url=url, error=str(exc))
            return None
