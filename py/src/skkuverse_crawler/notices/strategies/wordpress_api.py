from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import urljoin

from ...shared.fetcher import Fetcher
from ...shared.logger import get_logger
from ..models import NoticeDetail, NoticeListItem
from ..parser import load_html
from ..types import DetailRef

logger = get_logger("wordpress_api")

FILE_EXTENSIONS = re.compile(
    r"\.(pdf|hwp|hwpx|xlsx|xls|docx|doc|pptx|ppt|zip|rar|7z"
    r"|txt|csv|tsv|rtf|xml|json"
    r"|jpg|jpeg|png|gif|webp|bmp|tiff|svg"
    r"|mp3|mp4|mov|avi|mkv|wav)$",
    re.I,
)
UPLOADS_PATH = re.compile(r"/wp-content/uploads/", re.I)
WPDM_DOWNLOAD = re.compile(r"/download/\S+", re.I)


class WordPressApiStrategy:
    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher
        self._detail_cache: dict[int, NoticeDetail] = {}

    def _extract_attachments(self, html: str, base_url: str) -> list[dict[str, str]]:
        soup = load_html(html)
        attachments: list[dict[str, str]] = []
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if isinstance(href, list):
                href = href[0]
            if href and (FILE_EXTENSIONS.search(href) or UPLOADS_PATH.search(href) or WPDM_DOWNLOAD.search(href)):
                name = a.get_text(strip=True) or href.rsplit("/", 1)[-1] or "unknown"
                full_url = href if href.startswith("http") else urljoin(base_url, href)
                attachments.append({"name": name, "url": full_url})
        return attachments

    async def crawl_list(self, config: dict, page: int) -> list[NoticeListItem]:
        wp_page = page + 1
        params = (
            f"rest_route=/wp/v2/posts&per_page={config['pagination']['limit']}"
            f"&page={wp_page}&_fields=id,title,date,link,content,categories"
        )
        if config.get("categoryId"):
            params += f"&categories={config['categoryId']}"

        url = f"{config['baseUrl']}/?{params}"
        logger.info("fetching_wp_api", url=url, page=page)

        try:
            response = await self.fetcher.fetch(url)
            data = json.loads(response)
        except Exception as exc:
            # WP returns 400 when page exceeds total
            if hasattr(exc, "response") and getattr(exc.response, "status_code", 0) == 400:
                return []
            raise

        if not isinstance(data, list) or len(data) == 0:
            return []

        items: list[NoticeListItem] = []
        for post in data:
            article_no = post["id"]
            title = unescape(post.get("title", {}).get("rendered", ""))
            date = (post.get("date", "") or "").split("T")[0]
            detail_path = post.get("link", "")

            items.append(NoticeListItem(
                articleNo=article_no,
                title=title,
                category="",
                author="",
                date=date,
                views=0,
                detailPath=detail_path,
            ))

            # Cache detail from list response
            content_html = (post.get("content") or {}).get("rendered", "")
            if content_html:
                soup = load_html(content_html)
                content_text = soup.get_text(strip=True)
                attachments = self._extract_attachments(content_html, config["baseUrl"])
                self._detail_cache[article_no] = NoticeDetail(
                    content=content_html, contentText=content_text, attachments=attachments
                )

        return items

    async def crawl_detail(self, ref: DetailRef, config: dict) -> NoticeDetail | None:
        cached = self._detail_cache.pop(ref["articleNo"], None)
        if cached:
            return cached

        try:
            url = f"{config['baseUrl']}/?rest_route=/wp/v2/posts/{ref['articleNo']}&_fields=content"
            response = await self.fetcher.fetch(url)
            post = json.loads(response)
            content_html = (post.get("content") or {}).get("rendered", "")
            soup = load_html(content_html)
            return NoticeDetail(
                content=content_html,
                contentText=soup.get_text(strip=True),
                attachments=self._extract_attachments(content_html, config["baseUrl"]),
            )
        except Exception as exc:
            logger.error("wp_detail_failed", articleNo=ref["articleNo"], error=str(exc))
            return None
