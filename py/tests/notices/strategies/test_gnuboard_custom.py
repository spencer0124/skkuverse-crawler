from __future__ import annotations

from unittest.mock import AsyncMock

from skkuverse_crawler.notices.strategies.gnuboard_custom import GnuboardCustomStrategy


BASE_CONFIG = {
    "baseUrl": "https://nano.skku.edu/bbs/board.php",
    "boardParam": "tbl",
    "boardName": "bbs42",
    "articleIdParam": "num",
    "detailMode": "VIEW",
    "selectors": {
        "detailContent": "#DivContents",
        "detailAttachment": "a[href*='download.php']",
    },
}


def _make_strategy(html: str) -> GnuboardCustomStrategy:
    fetcher = AsyncMock()
    fetcher.fetch.return_value = html
    return GnuboardCustomStrategy(fetcher)


async def test_gnuboard_custom_attachment_includes_referer():
    """Attachment dict must include referer pointing to the detail page URL."""
    html = """
    <html><body>
      <div id="DivContents">본문 내용</div>
      <em>첨부파일</em>
      [<a href="/bbs/download.php?tbl=bbs42&no=419">졸업평가 FAQ.hwp</a>]
      | [<a href="/bbs/download.php?tbl=bbs42&no=420">결과보고서 양식.hwp</a>]
    </body></html>
    """
    strategy = _make_strategy(html)
    detail = await strategy.crawl_detail(
        {"articleNo": 416, "detailPath": "?tbl=bbs42&mode=VIEW&num=416"},
        BASE_CONFIG,
    )

    assert detail is not None
    assert len(detail.attachments) == 2

    att0 = detail.attachments[0]
    assert att0["name"] == "졸업평가 FAQ.hwp"
    assert att0["url"] == "https://nano.skku.edu/bbs/download.php?tbl=bbs42&no=419"
    assert att0["referer"] == "https://nano.skku.edu/bbs/board.php?tbl=bbs42&mode=VIEW&num=416"

    att1 = detail.attachments[1]
    assert att1["name"] == "결과보고서 양식.hwp"
    assert att1["referer"] == att0["referer"]  # same detail page


async def test_gnuboard_custom_attachment_referer_from_fallback():
    """When detailPath is empty, URL built from config params."""
    html = """
    <html><body>
      <div id="DivContents">본문</div>
      <a href="/bbs/download.php?tbl=bbs42&no=100">file.pdf</a>
    </body></html>
    """
    strategy = _make_strategy(html)
    detail = await strategy.crawl_detail(
        {"articleNo": 500, "detailPath": ""},
        BASE_CONFIG,
    )

    assert detail is not None
    assert len(detail.attachments) == 1
    assert detail.attachments[0]["referer"] == "https://nano.skku.edu/bbs/board.php?tbl=bbs42&mode=VIEW&num=500"


async def test_gnuboard_custom_no_attachment():
    html = """
    <html><body>
      <div id="DivContents">첨부 없는 게시글</div>
    </body></html>
    """
    strategy = _make_strategy(html)
    detail = await strategy.crawl_detail(
        {"articleNo": 1, "detailPath": "?tbl=bbs42&mode=VIEW&num=1"},
        BASE_CONFIG,
    )

    assert detail is not None
    assert detail.attachments == []
