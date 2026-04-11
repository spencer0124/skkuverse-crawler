from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class NoticeListItem:
    articleNo: int
    title: str
    category: str
    author: str
    date: str  # YYYY-MM-DD
    views: int
    detailPath: str  # relative or absolute URL to detail page


@dataclass
class NoticeDetail:
    content: str
    contentText: str
    attachments: list[dict[str, str]] = field(default_factory=list)  # [{name, url}]


@dataclass
class Notice:
    articleNo: int
    title: str
    category: str
    author: str
    department: str
    date: str  # YYYY-MM-DD
    views: int
    content: str | None
    contentText: str | None
    cleanHtml: str | None
    attachments: list[dict[str, str]]  # [{name, url}]
    sourceUrl: str
    detailPath: str
    sourceDeptId: str
    cleanMarkdown: str | None = None
    crawledAt: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    lastModified: str | None = None
    contentHash: str | None = None
    editHistory: list[dict[str, Any]] = field(default_factory=list)
    editCount: int = 0
    isDeleted: bool = False
    consecutiveFailures: int = 0
