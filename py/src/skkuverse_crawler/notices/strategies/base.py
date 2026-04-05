from __future__ import annotations

from typing import Protocol

from ..models import NoticeDetail, NoticeListItem
from ..types import DepartmentConfig, DetailRef


class CrawlStrategy(Protocol):
    async def crawl_list(self, config: DepartmentConfig, page: int) -> list[NoticeListItem]: ...
    async def crawl_detail(self, ref: DetailRef, config: DepartmentConfig) -> NoticeDetail | None: ...
