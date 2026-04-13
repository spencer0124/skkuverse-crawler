from __future__ import annotations

import json

from ...shared.fetcher import Fetcher
from ...shared.logger import get_logger
from ..models import NoticeDetail, NoticeListItem
from ..parser import load_html
from ..types import DetailRef

logger = get_logger("pyxis_api")

FRONTEND_BASE = "https://lib.skku.edu/hsc/bulletins/notice/notices"
ATTACHMENT_BASE = "https://lib.skku.edu/pyxis-api/attachments/BULLETIN"


class PyxisApiStrategy:
    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher
        self._attachment_cache: dict[int, list[dict[str, str]]] = {}

    async def crawl_list(self, config: dict, page: int) -> list[NoticeListItem]:  # type: ignore[override]
        limit = config["pagination"]["limit"]
        offset = page * limit
        board_id = config.get("bulletinBoardId", 1)

        url = f"{config['baseUrl']}/bulletin-boards/{board_id}/bulletins?max={limit}&offset={offset}"
        if config.get("bulletinCategoryId"):
            url += f"&bulletinCategoryId={config['bulletinCategoryId']}"

        logger.info("fetching_pyxis_api", url=url, page=page)

        try:
            response = await self.fetcher.fetch(url)
            envelope = json.loads(response)
        except Exception as exc:
            logger.error("pyxis_list_failed", page=page, error=str(exc))
            return []

        data = envelope.get("data")
        if not data or not envelope.get("success"):
            return []

        total_count = data.get("totalCount", 0)
        if offset >= total_count:
            return []

        items: list[NoticeListItem] = []
        for bulletin in data.get("list", []):
            article_no = bulletin["id"]
            cat = bulletin.get("bulletinCategory")
            category = cat["name"] if cat else ""
            date_raw = bulletin.get("dateCreated", "")
            date = date_raw[:10] if date_raw else ""

            items.append(NoticeListItem(
                articleNo=article_no,
                title=bulletin.get("title", ""),
                category=category,
                author=bulletin.get("writer", ""),
                date=date,
                views=bulletin.get("hitCnt", 0),
                detailPath=f"{FRONTEND_BASE}/{article_no}",
            ))

            # Cache attachments from list (list has physicalName, detail doesn't)
            attachments = self._build_attachments(bulletin.get("attachments", []))
            if attachments:
                self._attachment_cache[article_no] = attachments

        return items

    async def crawl_detail(self, ref: DetailRef, config: dict) -> NoticeDetail | None:  # type: ignore[override]
        article_no = ref["articleNo"]
        url = f"{config['baseUrl']}/bulletins/{article_no}"

        try:
            response = await self.fetcher.fetch(url)
            envelope = json.loads(response)
        except Exception as exc:
            logger.error("pyxis_detail_failed", articleNo=article_no, error=str(exc))
            return None

        data = envelope.get("data")
        if not data or not envelope.get("success"):
            return None

        content_html = data.get("content", "")
        soup = load_html(content_html)
        content_text = soup.get_text(strip=True)

        # Prefer cached attachments (list has physicalName for URL construction)
        attachments = self._attachment_cache.pop(article_no, None)
        if attachments is None:
            attachments = self._build_attachments(data.get("attachments", []))

        return NoticeDetail(
            content=content_html,
            contentText=content_text,
            attachments=attachments,
        )

    @staticmethod
    def _build_attachments(raw: list[dict]) -> list[dict[str, str]]:
        attachments: list[dict[str, str]] = []
        for att in raw:
            name = att.get("logicalName", "unknown")
            physical = att.get("physicalName", "")
            if physical:
                url = f"{ATTACHMENT_BASE}/{physical}"
            else:
                # Fallback: originalImageUrl is a relative path
                orig = att.get("originalImageUrl", "")
                url = f"https://lib.skku.edu/pyxis-api{orig}" if orig else ""
            if url:
                attachments.append({"name": name, "url": url})
        return attachments
