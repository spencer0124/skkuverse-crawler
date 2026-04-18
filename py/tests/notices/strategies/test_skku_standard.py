from __future__ import annotations

from unittest.mock import AsyncMock

from skkuverse_crawler.notices.strategies.skku_standard import SkkuStandardStrategy


# Subdomain template (cse.skku.edu, sw.skku.edu, skb.skku.edu, etc.)
SUBDOMAIN_CONFIG = {
    "baseUrl": "https://cse.skku.edu/cse/notice.do",
    "selectors": {
        "listItem": "dl.board-list-content-wrap",
        "category": "span.c-board-list-category",
        "titleLink": "dt.board-list-content-title a",
        "infoList": "dd.board-list-content-info ul li",
        "detailContent": "dl.board-write-box dd",
        "attachmentList": "ul.board-view-file-wrap li a",
    },
    "pagination": {"type": "offset", "param": "article.offset", "limit": 10},
}

# Main site template (www.skku.edu)
MAIN_SITE_CONFIG = {
    "baseUrl": "https://www.skku.edu/skku/campus/skk_comm/notice01.do",
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

# chem uses onclick parser
ONCLICK_CONFIG = {
    "baseUrl": "https://chem.skku.edu/chem/News/notice.do",
    "attachmentParser": "onclick",
    "selectors": {
        "listItem": "ul.noticeList > li",
        "category": "",
        "titleLink": "h3.noticeTit a",
        "infoList": "ul.noticeInfoList li",
        "detailContent": "div.noticeViewCont",
        "attachmentList": "div.noticeViewBtnList button.fileBtn",
    },
    "infoParser": "labeled",
    "pagination": {"type": "offset", "param": "article.offset", "limit": 10},
}


def _make_strategy(html: str) -> SkkuStandardStrategy:
    fetcher = AsyncMock()
    fetcher.fetch.return_value = html
    return SkkuStandardStrategy(fetcher)


def _detail_ref(article_no: int = 100) -> dict:
    return {"articleNo": article_no, "detailPath": f"?mode=view&articleNo={article_no}"}


# --- Subdomain template (board-view-file-wrap) ---


async def test_subdomain_attachment_parsed():
    """Subdomain sites use ul.board-view-file-wrap for attachments."""
    html = """
    <html><body>
      <dl class="board-write-box"><dd>본문 내용</dd></dl>
      <ul class="board-view-file-wrap">
        <li>
          <a class="file-down-btn pdf"
             href="?mode=download&amp;articleNo=100&amp;attachNo=999">
            공지사항.pdf
          </a>
        </li>
        <li>
          <a class="file-down-btn hwp"
             href="?mode=download&amp;articleNo=100&amp;attachNo=998">
            양식.hwp
          </a>
        </li>
      </ul>
    </body></html>
    """
    strategy = _make_strategy(html)
    detail = await strategy.crawl_detail(_detail_ref(), SUBDOMAIN_CONFIG)

    assert detail is not None
    assert len(detail.attachments) == 2
    assert detail.attachments[0]["name"] == "공지사항.pdf"
    assert detail.attachments[0]["url"] == "https://cse.skku.edu/cse/notice.do?mode=download&articleNo=100&attachNo=999"
    assert detail.attachments[1]["name"] == "양식.hwp"


# --- Main site template (filedown_list) ---


async def test_main_site_attachment_parsed():
    """www.skku.edu uses ul.filedown_list for attachments."""
    html = """
    <html><body>
      <dl class="board-write-box"><dd>본문 내용</dd></dl>
      <div class="file_downWrap">
        <ul class="filedown_list">
          <li>
            <a class="ellipsis" href="?mode=download&amp;articleNo=200&amp;attachNo=555">
              안내문.pdf
            </a>
          </li>
        </ul>
      </div>
    </body></html>
    """
    strategy = _make_strategy(html)
    detail = await strategy.crawl_detail(
        {"articleNo": 200, "detailPath": "?mode=view&articleNo=200"},
        MAIN_SITE_CONFIG,
    )

    assert detail is not None
    assert len(detail.attachments) == 1
    assert detail.attachments[0]["name"] == "안내문.pdf"
    assert detail.attachments[0]["url"] == "https://www.skku.edu/skku/campus/skk_comm/notice01.do?mode=download&articleNo=200&attachNo=555"


# --- No attachments ---


async def test_no_attachments_returns_empty_list():
    html = """
    <html><body>
      <dl class="board-write-box"><dd>첨부 없는 공지</dd></dl>
    </body></html>
    """
    strategy = _make_strategy(html)
    detail = await strategy.crawl_detail(_detail_ref(), SUBDOMAIN_CONFIG)

    assert detail is not None
    assert detail.attachments == []


# --- Relative URL resolution ---


async def test_relative_path_url_resolved():
    """Attachment href starting with / should resolve to origin."""
    html = """
    <html><body>
      <dl class="board-write-box"><dd>본문</dd></dl>
      <ul class="board-view-file-wrap">
        <li><a href="/common/filedown.do?fileId=abc123">첨부.xlsx</a></li>
      </ul>
    </body></html>
    """
    strategy = _make_strategy(html)
    detail = await strategy.crawl_detail(_detail_ref(), SUBDOMAIN_CONFIG)

    assert detail is not None
    assert len(detail.attachments) == 1
    assert detail.attachments[0]["url"] == "https://cse.skku.edu/common/filedown.do?fileId=abc123"


# --- onclick parser (chem) ---


async def test_onclick_parser_extracts_url():
    """attachmentParser=onclick extracts URL from onclick attribute."""
    html = """
    <html><body>
      <div class="noticeViewCont">화학과 공지</div>
      <div class="noticeViewBtnList">
        <button class="fileBtn"
                onclick="location.href='/chem/News/notice.do?mode=download&amp;articleNo=300&amp;attachNo=777'">
          실험안내.pdf
        </button>
      </div>
    </body></html>
    """
    strategy = _make_strategy(html)
    detail = await strategy.crawl_detail(
        {"articleNo": 300, "detailPath": "?mode=view&articleNo=300"},
        ONCLICK_CONFIG,
    )

    assert detail is not None
    assert len(detail.attachments) == 1
    assert detail.attachments[0]["name"] == "실험안내.pdf"
    assert detail.attachments[0]["url"] == "https://chem.skku.edu/chem/News/notice.do?mode=download&articleNo=300&attachNo=777"


# --- href="#" filtered out ---


async def test_hash_href_filtered_out():
    """Links with href='#' should be excluded from attachments."""
    html = """
    <html><body>
      <dl class="board-write-box"><dd>본문</dd></dl>
      <ul class="board-view-file-wrap">
        <li><a href="#">파일 아닌 링크</a></li>
        <li><a href="?mode=download&amp;articleNo=100&amp;attachNo=111">실제파일.pdf</a></li>
      </ul>
    </body></html>
    """
    strategy = _make_strategy(html)
    detail = await strategy.crawl_detail(_detail_ref(), SUBDOMAIN_CONFIG)

    assert detail is not None
    assert len(detail.attachments) == 1
    assert detail.attachments[0]["name"] == "실제파일.pdf"
