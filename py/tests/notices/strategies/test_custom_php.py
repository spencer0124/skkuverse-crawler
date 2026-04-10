from __future__ import annotations

from unittest.mock import AsyncMock

from skkuverse_crawler.notices.strategies.custom_php import CustomPhpStrategy


BASE_CONFIG = {
    "baseUrl": "https://cal.skku.edu/index.php",
    "boardParams": {"hCode": "BOARD", "bo_idx": "17"},
    "selectors": {
        "detailContent": "div.board_content",
        "detailAttachment": "div.attachment a[href]",
    },
}


def _make_strategy(html: str) -> CustomPhpStrategy:
    fetcher = AsyncMock()
    fetcher.fetch.return_value = html
    return CustomPhpStrategy(fetcher)


async def test_custom_php_attachment_extraction_prefers_name_param():
    """실제 cal.skku.edu 패턴: 링크 텍스트는 '내 pc저장' 버튼, 파일명은 name= 쿼리에."""
    html = """
    <html><body>
      <div class="board_content">본문 내용</div>
      <div class="attachment">
        <a href="./NFUpload/nfupload_down.php?tmp_name=abc.jpg&name=%EB%8C%80%ED%95%9C%ED%86%A0%EB%AA%A9%ED%95%99%ED%9A%8C.jpg">내 pc저장</a>
        <a href="./NFUpload/nfupload_down.php?tmp_name=doc.pdf&name=notice.pdf">내 pc저장</a>
      </div>
    </body></html>
    """
    strategy = _make_strategy(html)
    detail = await strategy.crawl_detail(
        {"articleNo": 1309, "detailPath": "?hCode=BOARD&bo_idx=17&page=view&idx=1309"},
        BASE_CONFIG,
    )

    assert detail is not None
    assert len(detail.attachments) == 2
    assert detail.attachments[0]["name"] == "대한토목학회.jpg"
    assert detail.attachments[1]["name"] == "notice.pdf"
    assert detail.attachments[0]["url"].startswith("https://cal.skku.edu/NFUpload/nfupload_down.php?")


async def test_custom_php_attachment_falls_back_to_link_text():
    """name= 파라미터가 없으면 링크 텍스트를 파일명으로 사용."""
    html = """
    <html><body>
      <div class="board_content">본문</div>
      <div class="attachment">
        <a href="./files/plain.pdf">plain.pdf</a>
      </div>
    </body></html>
    """
    strategy = _make_strategy(html)
    detail = await strategy.crawl_detail(
        {"articleNo": 1, "detailPath": "?page=view&idx=1"},
        BASE_CONFIG,
    )

    assert detail is not None
    assert len(detail.attachments) == 1
    assert detail.attachments[0]["name"] == "plain.pdf"


async def test_custom_php_no_attachment():
    html = """
    <html><body>
      <div class="board_content">본문만 있음</div>
    </body></html>
    """
    strategy = _make_strategy(html)
    detail = await strategy.crawl_detail(
        {"articleNo": 1310, "detailPath": "?page=view&idx=1310"},
        BASE_CONFIG,
    )

    assert detail is not None
    assert detail.attachments == []
    assert "본문만 있음" in detail.contentText


async def test_custom_php_absolute_href_preserved():
    html = """
    <html><body>
      <div class="board_content">x</div>
      <div class="attachment">
        <a href="https://example.com/files/a.pdf">외부파일.pdf</a>
      </div>
    </body></html>
    """
    strategy = _make_strategy(html)
    detail = await strategy.crawl_detail(
        {"articleNo": 1, "detailPath": "?page=view&idx=1"},
        BASE_CONFIG,
    )

    assert detail is not None
    assert detail.attachments[0]["url"] == "https://example.com/files/a.pdf"
