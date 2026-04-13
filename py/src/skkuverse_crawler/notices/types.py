from __future__ import annotations

from typing import Literal, Protocol, TypedDict

from .models import NoticeDetail, NoticeListItem


# ── Pagination ──────────────────────────────────────────

class OffsetPaginationConfig(TypedDict):
    type: Literal["offset"]
    param: str
    limit: int


class PageNumPaginationConfig(TypedDict):
    type: Literal["pageNum"]
    param: str
    limit: int


PaginationConfig = OffsetPaginationConfig | PageNumPaginationConfig


# ── Department Config ───────────────────────────────────
# camelCase keys match departments.json field names

class SkkuStandardSelectors(TypedDict):
    listItem: str
    category: str
    titleLink: str
    infoList: str
    detailContent: str
    attachmentList: str


class SkkuStandardDepartmentConfig(TypedDict, total=False):
    id: str
    name: str
    strategy: Literal["skku-standard"]
    baseUrl: str
    pagination: OffsetPaginationConfig
    selectors: SkkuStandardSelectors
    extraParams: dict[str, str]
    infoParser: Literal["standard", "labeled"]
    attachmentParser: Literal["href", "onclick"]


class WordPressApiDepartmentConfig(TypedDict, total=False):
    id: str
    name: str
    strategy: Literal["wordpress-api"]
    baseUrl: str
    pagination: PageNumPaginationConfig
    extraParams: dict[str, str]
    categoryId: int


class SkkumedAspSelectors(TypedDict):
    listItem: str
    titleLink: str
    infoList: str
    detailContent: str
    attachmentList: str


class SkkumedAspDepartmentConfig(TypedDict, total=False):
    id: str
    name: str
    strategy: Literal["skkumed-asp"]
    baseUrl: str
    pagination: PageNumPaginationConfig
    encoding: str
    detailBaseUrl: str
    selectors: SkkumedAspSelectors
    extraParams: dict[str, str]


class JspDormSelectors(TypedDict):
    listRow: str
    pinnedRow: str
    titleLink: str
    detailContent: str
    attachmentLink: str


class JspDormDepartmentConfig(TypedDict, total=False):
    id: str
    name: str
    strategy: Literal["jsp-dorm"]
    baseUrl: str
    pagination: OffsetPaginationConfig
    boardNo: str
    selectors: JspDormSelectors
    extraParams: dict[str, str]


class CustomPhpSelectors(TypedDict):
    listRow: str
    titleLink: str
    category: str
    views: str
    date: str
    detailContent: str


class CustomPhpDepartmentConfig(TypedDict, total=False):
    id: str
    name: str
    strategy: Literal["custom-php"]
    baseUrl: str
    pagination: PageNumPaginationConfig
    boardParams: dict[str, str]
    articleIdParam: str
    selectors: CustomPhpSelectors
    extraParams: dict[str, str]


class GnuboardSelectors(TypedDict, total=False):
    listRow: str
    titleLink: str
    titleText: str
    author: str
    views: str
    date: str
    detailContent: str
    detailAttachment: str


class GnuboardDepartmentConfig(TypedDict, total=False):
    id: str
    name: str
    strategy: Literal["gnuboard"]
    baseUrl: str
    pagination: PageNumPaginationConfig
    boardParam: str
    boardName: str
    articleIdParam: str
    skinType: Literal["table", "list"]
    selectors: GnuboardSelectors
    extraParams: dict[str, str]


class GnuboardCustomSelectors(TypedDict):
    listRow: str
    titleLink: str
    date: str
    meta: str
    detailContent: str
    detailAttachment: str


class GnuboardCustomDepartmentConfig(TypedDict, total=False):
    id: str
    name: str
    strategy: Literal["gnuboard-custom"]
    baseUrl: str
    pagination: PageNumPaginationConfig
    boardParam: str
    boardName: str
    articleIdParam: str
    detailMode: str
    selectors: GnuboardCustomSelectors
    extraParams: dict[str, str]


class PyxisApiDepartmentConfig(TypedDict, total=False):
    id: str
    name: str
    strategy: Literal["pyxis-api"]
    baseUrl: str
    pagination: OffsetPaginationConfig
    bulletinBoardId: int
    bulletinCategoryId: int


DepartmentConfig = (
    SkkuStandardDepartmentConfig
    | WordPressApiDepartmentConfig
    | SkkumedAspDepartmentConfig
    | JspDormDepartmentConfig
    | CustomPhpDepartmentConfig
    | GnuboardDepartmentConfig
    | GnuboardCustomDepartmentConfig
    | PyxisApiDepartmentConfig
)


# ── Strategy ────────────────────────────────────────────

class DetailRef(TypedDict):
    articleNo: int
    detailPath: str


class CrawlStrategy(Protocol):
    async def crawl_list(self, config: DepartmentConfig, page: int) -> list[NoticeListItem]: ...
    async def crawl_detail(self, ref: DetailRef, config: DepartmentConfig) -> NoticeDetail | None: ...
