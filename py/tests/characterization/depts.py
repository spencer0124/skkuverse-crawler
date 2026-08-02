"""Synthetic department configs for the golden crawls.

Deliberately NOT read from sources.json: the goldens must not move when live
source data churns, and the only real wordpress-api source (cheme) is
disabled anyway (user decision: wordpress-api is out of the golden matrix).
Selector/pagination shapes are copied from the real `skku-main` and
`bio-undergrad` entries so strategy parsing stays production-shaped; hosts
use the reserved `.test` TLD so a routing gap can never hit a real server.
"""
from __future__ import annotations

SKKU_STD_DEPT: dict = {
    "id": "golden-std",
    "name": "골든 표준 게시판",
    "strategy": "skku-standard",
    "crawlAvailable": True,
    "crawlEnabled": True,
    "baseUrl": "https://skku-std.test/board/notice.do",
    "selectors": {
        "listItem": "dl.board-list-content-wrap",
        "category": "span.c-board-list-category",
        "titleLink": "dt.board-list-content-title a",
        "infoList": "dd.board-list-content-info ul li",
        "detailContent": "dl.board-write-box dd",
        "attachmentList": "ul.filedown_list li a",
    },
    "pagination": {"type": "offset", "param": "article.offset", "limit": 10},
}

GNUBOARD_DEPT: dict = {
    "id": "golden-gnb",
    "name": "골든 그누보드",
    "strategy": "gnuboard",
    "crawlAvailable": True,
    "crawlEnabled": True,
    "baseUrl": "http://gnb.test/bbs/board.php",
    "boardParam": "bo_table",
    "boardName": "N4",
    "articleIdParam": "wr_id",
    "skinType": "table",
    "selectors": {
        "listRow": "#bo_list .spage table.table tbody tr",
        "titleLink": "td:nth-child(2) a",
        "author": "td:nth-child(3) .sv_member",
        "views": "td:nth-child(4)",
        "date": "td:nth-child(5)",
        "detailContent": "#bo_v_con",
        "detailAttachment": "#bo_v_file ul li a.view_file_download",
    },
    "pagination": {"type": "pageNum", "param": "page", "limit": 15},
}


def std_list_url(page: int) -> str:
    return (
        f"{SKKU_STD_DEPT['baseUrl']}?mode=list&articleLimit=10&article.offset={page * 10}"
    )


def std_detail_url(article_no: int) -> str:
    return (
        f"{SKKU_STD_DEPT['baseUrl']}"
        f"?mode=view&articleNo={article_no}&article.offset=0&articleLimit=10"
    )


def gnb_list_url(page: int) -> str:
    return f"{GNUBOARD_DEPT['baseUrl']}?bo_table=N4&page={page + 1}"


def gnb_detail_url(article_no: int) -> str:
    return f"{GNUBOARD_DEPT['baseUrl']}?bo_table=N4&wr_id={article_no}"
