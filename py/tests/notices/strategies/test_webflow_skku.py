from __future__ import annotations

from unittest.mock import AsyncMock

from skkuverse_crawler.notices.strategies.webflow_skku import (
    WebflowSkkuStrategy,
    slug_to_article_no,
)


BASE_CONFIG = {
    "baseUrl": "https://ott.skku.edu/ftm-skku-edu/notice",
    "pageParam": "671fdbc7_page",
    "selectors": {
        "listItem": "div.w-dyn-list div.w-dyn-item",
        "listLink": "a.link-block-3",
        "listRow": "div.table-line-copy",
        "titleCell": "div.text-block-8-copy",
        "regularCell": "div.text-block-8",
        "paginationNext": "a.w-pagination-next",
        "detailTitle": "h1.heading-19",
        "detailContent": "div.rich-text-block-3.w-richtext",
    },
}


def _row_html(
    number: str,
    category: str,
    title: str,
    author: str,
    date: str,
    slug: str = "sample-notice",
    *,
    include_link: bool = True,
) -> str:
    href = f"/yeongsanghaggwa-notice/{slug}"
    link_open = (
        f'<a class="link-block-3 w-inline-block" href="{href}">' if include_link else ""
    )
    link_close = "</a>" if include_link else ""
    return f"""
    <div role="listitem" class="collection-item-5 w-dyn-item">
      {link_open}
        <div class="table-line-copy">
          <div class="text-block-8">{number}</div>
          <div class="text-block-8">{category}</div>
          <div class="text-block-8-copy">{title}</div>
          <div class="text-block-8">{author}</div>
          <div class="text-block-8">{date}</div>
        </div>
      {link_close}
    </div>
    """


def _list_html(rows: list[str], next_token: str | None = "671fdbc7_page") -> str:
    next_anchor = (
        f'<a href="?{next_token}=2" class="w-pagination-next">다음</a>' if next_token else ""
    )
    items_html = "\n".join(rows)
    return f"""
    <html><body>
      <div class="w-dyn-list">
        <div role="list" class="w-dyn-items">
          {items_html}
        </div>
        <div class="w-pagination-wrapper">{next_anchor}</div>
      </div>
    </body></html>
    """


def _make_strategy(html_or_list) -> WebflowSkkuStrategy:
    fetcher = AsyncMock()
    if isinstance(html_or_list, list):
        fetcher.fetch.side_effect = html_or_list
    else:
        fetcher.fetch.return_value = html_or_list
    return WebflowSkkuStrategy(fetcher)


# ── 1. List parses 10 items ──────────────────────────────────


async def test_crawl_list_parses_ten_items():
    rows = [
        _row_html(
            str(42 - i),
            "영상학과",
            f"공지 #{42 - i}",
            "영상학과",
            "2026. 05. 19.",
            slug=f"notice-{42 - i}",
        )
        for i in range(10)
    ]
    html = _list_html(rows)
    strategy = _make_strategy(html)
    items = await strategy.crawl_list(BASE_CONFIG, page=0)

    assert len(items) == 10
    assert items[0].title == "공지 #42"
    assert items[0].category == "영상학과"
    assert items[0].author == "영상학과"
    assert items[0].date == "2026-05-19"
    assert items[0].views == 0
    assert items[0].detailPath == "https://ott.skku.edu/yeongsanghaggwa-notice/notice-42"
    assert items[0].articleNo > 0


# ── 2. Hidden template row (no link) is filtered out ─────────


async def test_crawl_list_filters_template_item():
    real_row = _row_html("1", "영상학과", "실제 공지", "영상학과", "2026. 01. 01.")
    template_row = _row_html(
        "", "", "", "", "", slug="x", include_link=False
    )
    html = _list_html([template_row, real_row, template_row])
    strategy = _make_strategy(html)
    items = await strategy.crawl_list(BASE_CONFIG, page=0)

    assert len(items) == 1
    assert items[0].title == "실제 공지"


# ── 3. slug → int hash is stable + positive ──────────────────


def test_slug_to_article_no_stable_and_positive():
    slug = "jungyo-2026hagnyeondo-1haggi-yesim-sigan-baejeong"
    a = slug_to_article_no(slug)
    b = slug_to_article_no(slug)
    assert a == b
    # 7-byte digest → 56-bit positive int (fits BSON Long signed int64)
    assert 0 < a < 2**56

    # Different slugs produce different ints (sanity, not strict)
    assert slug_to_article_no("foo") != slug_to_article_no("bar")


# ── 4. Date normalization ────────────────────────────────────


async def test_crawl_list_normalizes_date():
    row = _row_html("1", "cat", "t", "author", "2026. 05. 19.")
    strategy = _make_strategy(_list_html([row]))
    items = await strategy.crawl_list(BASE_CONFIG, page=0)
    assert items[0].date == "2026-05-19"


async def test_crawl_list_normalizes_date_single_digit_month():
    row = _row_html("1", "cat", "t", "author", "2026. 1. 9.")
    strategy = _make_strategy(_list_html([row]))
    items = await strategy.crawl_list(BASE_CONFIG, page=0)
    assert items[0].date == "2026-01-09"


async def test_crawl_list_normalizes_two_digit_year():
    # Source uses "24.09.19." form for some older posts — assume 20XX
    row = _row_html("1", "cat", "t", "author", "24.09.19.")
    strategy = _make_strategy(_list_html([row]))
    items = await strategy.crawl_list(BASE_CONFIG, page=0)
    assert items[0].date == "2024-09-19"


async def test_crawl_list_normalizes_two_digit_year_no_trailing_dot():
    row = _row_html("1", "cat", "t", "author", "24.09.08")
    strategy = _make_strategy(_list_html([row]))
    items = await strategy.crawl_list(BASE_CONFIG, page=0)
    assert items[0].date == "2024-09-08"


# ── 5. Detail extracts body and title ────────────────────────


async def test_crawl_detail_extracts_body_and_title():
    html = """
    <html><body>
      <section class="section notice-copy">
        <div class="div-block-19">
          <h1 class="heading-19">[중요] 2026 안내</h1>
          <div class="text-block-16">2026. 05. 19.</div>
        </div>
        <div class="rich-text-block-3 w-richtext">
          <p>본문 첫 문단입니다.</p>
          <p><strong>강조 부분</strong></p>
        </div>
      </section>
    </body></html>
    """
    strategy = _make_strategy(html)
    detail = await strategy.crawl_detail(
        {
            "articleNo": 123,
            "detailPath": "https://ott.skku.edu/yeongsanghaggwa-notice/test",
        },
        BASE_CONFIG,
    )

    assert detail is not None
    assert detail.title == "[중요] 2026 안내"
    assert "본문 첫 문단입니다." in detail.contentText
    assert "강조 부분" in detail.contentText
    assert "<strong>강조 부분</strong>" in detail.content


# ── 6. Detail extracts file attachments by extension ─────────


async def test_crawl_detail_extracts_file_attachments():
    html = """
    <html><body>
      <h1 class="heading-19">첨부 있는 공지</h1>
      <div class="rich-text-block-3 w-richtext">
        <p>본문</p>
        <p><a href="/files/notice-2026.pdf">공지문.pdf</a></p>
        <p><a href="https://cdn.example.com/form.hwp">양식.hwp</a></p>
        <p><a href="https://ott.skku.edu/page">관련 페이지</a></p>
      </div>
    </body></html>
    """
    strategy = _make_strategy(html)
    detail = await strategy.crawl_detail(
        {
            "articleNo": 1,
            "detailPath": "https://ott.skku.edu/yeongsanghaggwa-notice/attach-test",
        },
        BASE_CONFIG,
    )

    assert detail is not None
    assert len(detail.attachments) == 2
    names = [a["name"] for a in detail.attachments]
    urls = [a["url"] for a in detail.attachments]
    assert "공지문.pdf" in names
    assert "양식.hwp" in names
    assert "https://ott.skku.edu/files/notice-2026.pdf" in urls
    assert "https://cdn.example.com/form.hwp" in urls


# ── 7. Pagination URL: page=0 uses bare baseUrl; page>=1 uses token ──


async def test_pagination_urls():
    page1_html = _list_html(
        [_row_html("1", "c", "t1", "a", "2026. 01. 01.")],
        next_token="671fdbc7_page",
    )
    page2_html = _list_html(
        [_row_html("2", "c", "t2", "a", "2026. 01. 02.")],
        next_token=None,
    )
    strategy = _make_strategy([page1_html, page2_html])

    await strategy.crawl_list(BASE_CONFIG, page=0)
    await strategy.crawl_list(BASE_CONFIG, page=1)

    calls = [c.args[0] for c in strategy.fetcher.fetch.call_args_list]
    assert calls[0] == "https://ott.skku.edu/ftm-skku-edu/notice"
    assert calls[1] == "https://ott.skku.edu/ftm-skku-edu/notice?671fdbc7_page=2"


# ── 8. Pagination token autodiscovery overrides configured ───


async def test_pagination_token_autodiscovery():
    """If site is republished with a new token, strategy discovers it from the
    next-link href on page 0 and uses it for subsequent pages."""
    # Webflow always emits lowercase-hex tokens (8 chars from the data-w-id)
    stale_config = {**BASE_CONFIG, "pageParam": "deadbeef_page"}

    page1_html = _list_html(
        [_row_html("1", "c", "t1", "a", "2026. 01. 01.")],
        next_token="cafe1234_page",  # site's actual current token
    )
    page2_html = _list_html(
        [_row_html("2", "c", "t2", "a", "2026. 01. 02.")],
        next_token=None,
    )
    strategy = _make_strategy([page1_html, page2_html])

    await strategy.crawl_list(stale_config, page=0)
    await strategy.crawl_list(stale_config, page=1)

    calls = [c.args[0] for c in strategy.fetcher.fetch.call_args_list]
    # page 0 is fetched bare (no token used)
    assert calls[0] == "https://ott.skku.edu/ftm-skku-edu/notice"
    # page 1 must use the DISCOVERED token, not the stale configured one
    assert calls[1] == "https://ott.skku.edu/ftm-skku-edu/notice?cafe1234_page=2"


# ── 9. Detail fetch failure returns None ─────────────────────


async def test_crawl_detail_returns_none_on_fetch_failure():
    fetcher = AsyncMock()
    fetcher.fetch.side_effect = RuntimeError("network down")
    strategy = WebflowSkkuStrategy(fetcher)
    detail = await strategy.crawl_detail(
        {
            "articleNo": 1,
            "detailPath": "https://ott.skku.edu/yeongsanghaggwa-notice/x",
        },
        BASE_CONFIG,
    )
    assert detail is None


# ── 10. Missing detailContent selector yields empty strings ──


async def test_crawl_detail_empty_content_when_selector_misses():
    """Selector mismatch must not crash; orchestrator still receives a Notice."""
    html = """
    <html><body>
      <h1 class="heading-19">제목만 있음</h1>
    </body></html>
    """
    strategy = _make_strategy(html)
    detail = await strategy.crawl_detail(
        {
            "articleNo": 1,
            "detailPath": "https://ott.skku.edu/yeongsanghaggwa-notice/x",
        },
        BASE_CONFIG,
    )
    assert detail is not None
    assert detail.title == "제목만 있음"
    assert detail.content == ""
    assert detail.contentText == ""
    assert detail.attachments == []


# ── 11. Protocol-relative attachment URL is upgraded to https ──


async def test_crawl_detail_protocol_relative_attachment():
    html = """
    <html><body>
      <h1 class="heading-19">t</h1>
      <div class="rich-text-block-3 w-richtext">
        <p><a href="//cdn.example.com/files/notice.pdf">자료.pdf</a></p>
      </div>
    </body></html>
    """
    strategy = _make_strategy(html)
    detail = await strategy.crawl_detail(
        {
            "articleNo": 1,
            "detailPath": "https://ott.skku.edu/yeongsanghaggwa-notice/x",
        },
        BASE_CONFIG,
    )
    assert detail is not None
    assert len(detail.attachments) == 1
    assert detail.attachments[0]["url"] == "https://cdn.example.com/files/notice.pdf"
