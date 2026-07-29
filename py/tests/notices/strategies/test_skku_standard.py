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


LIST_PAGE_WITH_PINNED = """
<div>
  <dl class="board-list-content-wrap ">
    <dt class="board-list-content-title ">
      <a href="?mode=view&articleNo=210001&article.offset=0&articleLimit=10" title="자세히 보기">고정 공지</a>
    </dt>
    <dd class="board-list-content-info">
      <ul><li>공지</li><li>글로벌융합학부</li><li>2026-05-01</li><li>조회수<span>100</span></li></ul>
    </dd>
  </dl>
  <dl class="board-list-content-wrap ">
    <dt class="board-list-content-title ">
      <a href="?mode=view&articleNo=210002&article.offset=0&articleLimit=10" title="자세히 보기">일반 공지</a>
    </dt>
    <dd class="board-list-content-info">
      <ul><li>No.756</li><li>글로벌융합학부</li><li>2026-06-01</li><li>조회수<span>10</span></li></ul>
    </dd>
  </dl>
</div>
"""


async def test_crawl_list_detects_pinned_rows():
    """첫 info 셀이 '공지'인 행은 pinned=True, 'No.###'인 행은 False."""
    strategy = _make_strategy(LIST_PAGE_WITH_PINNED)
    items = await strategy.crawl_list(SUBDOMAIN_CONFIG, page=0)

    assert len(items) == 2
    by_no = {i.articleNo: i for i in items}
    assert by_no[210001].pinned is True
    assert by_no[210002].pinned is False
    assert by_no[210001].date == "2026-05-01"
    assert by_no[210002].views == 10


# --- hakbu boards (viewBoardId/itemId links, hex-UNID legacy rows) ---

# hakbu.skku.edu notice_total.do template (post-2026-07 CMS restructure)
HAKBU_PORTAL_CONFIG = {
    "baseUrl": "https://hakbu.skku.edu/hakbu/notice_total.do",
    "selectors": {
        "listItem": "dl.board-list-content-wrap",
        "category": "span.c-board-list-category",
        "titleLink": "dt.board-list-content-title a",
        "infoList": "dd.board-list-content-info ul li",
        "detailContent": "dl.board-write-box dd",
        "attachmentList": "ul.board-view-file-wrap li a",
    },
    "pagination": {"type": "offset", "param": "article.offset", "limit": 10},
    "extraParams": {"boardId": "138880"},
}

HAKBU_LIST_PAGE = """
<div>
  <dl class="board-list-content-wrap">
    <dt class="board-list-content-title ">
      <span class="c-board-list-category" data-board-id="138880">[수강신청공지]</span>
      <a href="?mode=view&link=null&amp;viewBoardId=138880&amp;itemId=161037&amp;article.offset=0&amp;articleLimit=10" title="자세히 보기">수강신청 안내</a>
    </dt>
    <dd class="board-list-content-info">
      <ul><li>No.399</li><li>학부대학</li><li>2026-07-29 16:55</li></ul>
    </dd>
  </dl>
  <dl class="board-list-content-wrap">
    <dt class="board-list-content-title ">
      <span class="c-board-list-category" data-board-id="138880">[수강신청공지]</span>
      <a href="?mode=view&link=null&amp;viewBoardId=138880&amp;itemId=75E2890A6B96EC7B49258B9D000ABFDE&amp;article.offset=0&amp;articleLimit=10" title="자세히 보기">숫자로 시작하는 레거시 UNID</a>
    </dt>
    <dd class="board-list-content-info">
      <ul><li>No.120</li><li>학부대학</li><li>2024-09-26 10:00</li></ul>
    </dd>
  </dl>
  <dl class="board-list-content-wrap">
    <dt class="board-list-content-title ">
      <span class="c-board-list-category" data-board-id="138880">[수강신청공지]</span>
      <a href="?mode=view&link=null&amp;viewBoardId=138880&amp;itemId=C3FE59C22428B09249258BDA005C233F&amp;article.offset=0&amp;articleLimit=10" title="자세히 보기">문자로 시작하는 레거시 UNID</a>
    </dt>
    <dd class="board-list-content-info">
      <ul><li>No.119</li><li>학부대학</li><li>2024-11-26 10:00</li></ul>
    </dd>
  </dl>
</div>
"""


async def test_hakbu_numeric_item_id_parsed():
    """새 hakbu 링크 포맷(viewBoardId+itemId)에서 숫자 itemId를 articleNo로 추출."""
    strategy = _make_strategy(HAKBU_LIST_PAGE)
    items = await strategy.crawl_list(HAKBU_PORTAL_CONFIG, page=0)

    assert len(items) == 1
    item = items[0]
    assert item.articleNo == 161037
    assert item.category == "수강신청공지"
    assert item.author == "학부대학"
    assert item.date == "2026-07-29 16:55"
    assert item.views == 0  # 새 보드 info는 3열(번호/작성자/일시) — 조회수 없음
    assert item.pinned is False


async def test_hakbu_hex_unid_rows_skipped():
    """레거시 hex UNID 행은 skip — 특히 숫자로 시작하는 UNID(75E2…)가
    articleNo=75로 오추출되지 않아야 한다."""
    strategy = _make_strategy(HAKBU_LIST_PAGE)
    items = await strategy.crawl_list(HAKBU_PORTAL_CONFIG, page=0)

    parsed_nos = {i.articleNo for i in items}
    assert 75 not in parsed_nos
    assert parsed_nos == {161037}


async def test_hakbu_list_url_includes_board_filter():
    """extraParams.boardId가 리스트 URL 쿼리에 포함되어야 한다."""
    strategy = _make_strategy(HAKBU_LIST_PAGE)
    await strategy.crawl_list(HAKBU_PORTAL_CONFIG, page=0)

    fetched_url = strategy.fetcher.fetch.await_args.args[0]
    assert fetched_url == (
        "https://hakbu.skku.edu/hakbu/notice_total.do"
        "?boardId=138880&mode=list&articleLimit=10&article.offset=0"
    )
