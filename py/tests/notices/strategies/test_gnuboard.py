from __future__ import annotations

from unittest.mock import AsyncMock

from skkuverse_crawler.notices.strategies.gnuboard import GnuboardStrategy


BASE_CONFIG = {
    "baseUrl": "https://pharm.skku.edu/bbs/board.php",
    "boardParam": "bo_table",
    "boardName": "notice",
    "articleIdParam": "wr_id",
    "skinType": "list",
    "selectors": {
        "detailContent": "#bo_v_con",
        "detailAttachment": "div.bo_file_layer ul li a",
    },
}


def _make_strategy(html: str) -> GnuboardStrategy:
    fetcher = AsyncMock()
    fetcher.fetch.return_value = html
    return GnuboardStrategy(fetcher)


async def test_gnuboard_attachment_includes_referer():
    """Attachment dict must include referer pointing to the detail page URL."""
    html = """
    <html><body>
      <div id="bo_v_con">본문 내용</div>
      <div class="bo_file_layer"><ul>
        <li><a href="/bbs/download.php?bo_table=notice&wr_id=100&no=0&page=1">첨부파일.pdf</a></li>
      </ul></div>
    </body></html>
    """
    strategy = _make_strategy(html)
    detail = await strategy.crawl_detail(
        {"articleNo": 100, "detailPath": "?bo_table=notice&wr_id=100"},
        BASE_CONFIG,
    )

    assert detail is not None
    assert len(detail.attachments) == 1
    att = detail.attachments[0]
    assert att["name"] == "첨부파일.pdf"
    assert att["url"] == "https://pharm.skku.edu/bbs/download.php?bo_table=notice&wr_id=100&no=0&page=1"
    assert att["referer"] == "https://pharm.skku.edu/bbs/board.php?bo_table=notice&wr_id=100"


async def test_gnuboard_attachment_referer_from_detailpath_fallback():
    """When detailPath doesn't start with ? or http, URL is built from config."""
    html = """
    <html><body>
      <div id="bo_v_con">본문</div>
      <div class="bo_file_layer"><ul>
        <li><a href="/bbs/download.php?bo_table=notice&wr_id=200&no=0">file.hwp</a></li>
      </ul></div>
    </body></html>
    """
    strategy = _make_strategy(html)
    detail = await strategy.crawl_detail(
        {"articleNo": 200, "detailPath": ""},
        BASE_CONFIG,
    )

    assert detail is not None
    assert len(detail.attachments) == 1
    # Falls back to constructed URL from config
    assert detail.attachments[0]["referer"] == "https://pharm.skku.edu/bbs/board.php?bo_table=notice&wr_id=200"


async def test_gnuboard_no_attachment_empty_list():
    html = """
    <html><body>
      <div id="bo_v_con">본문만 있음</div>
    </body></html>
    """
    strategy = _make_strategy(html)
    detail = await strategy.crawl_detail(
        {"articleNo": 300, "detailPath": "?bo_table=notice&wr_id=300"},
        BASE_CONFIG,
    )

    assert detail is not None
    assert detail.attachments == []
