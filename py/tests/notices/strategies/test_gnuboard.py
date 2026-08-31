from __future__ import annotations

from unittest.mock import AsyncMock

from skkuverse_crawler.modules.notices.strategies.gnuboard import (
    GnuboardStrategy,
    normalize_date,
    parse_article_no,
)


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


# ---------------------------------------------------------------------------
# saint: gnuboard5 with mod_rewrite on and a themed date column
#
# The site was rebuilt from a Java CMS onto gnuboard in Aug 2026 (the old
# .do URL now 404s). Its markup is stock gnuboard, but two details break the
# parser's original assumptions: list links carry no wr_id= because rewrite
# is on, and the theme renders dates as "MM.DD YYYY". Both failures are
# silent — they drop rows inside the per-row except and leave a source that
# fetches 200 OK and stores nothing (known-issues §12c), so these tests pin
# the fallbacks rather than the happy path alone.
# ---------------------------------------------------------------------------

SAINT_CONFIG = {
    "baseUrl": "https://saint.skku.edu/bbs/board.php",
    "boardParam": "bo_table",
    "boardName": "05_03",
    "articleIdParam": "wr_id",
    "skinType": "table",
    # No "author": the board has a No/Title/Date table and nothing else.
    # No "detailAttachment": downloads are behind a member login.
    "selectors": {
        "listRow": "#bo_list .tbl_head01 table tbody tr",
        "titleLink": "td.td_subject .bo_tit a",
        "date": "td.td_datetime",
        "detailContent": "#bo_v_con",
    },
}

SAINT_LIST_HTML = """
<div id="bo_list">
  <div class="tbl_head01 tbl_wrap"><table><tbody>
    <tr class="">
      <td class="td_num2">414</td>
      <td class="td_subject"><div class="bo_tit">
        <a href="https://saint.skku.edu/05_03/473"><span class="ti">논문제출자격시험 안내</span></a>
      </div></td>
      <td class="td_datetime">08.20 2026</td>
    </tr>
    <tr class="">
      <td class="td_num2">413</td>
      <td class="td_subject"><div class="bo_tit">
        <a href="https://saint.skku.edu/05_03/444?page=2"><span class="ti">학위수여식 안내</span></a>
      </div></td>
      <td class="td_datetime">08.11 2026</td>
    </tr>
  </tbody></table></div>
</div>
"""


class TestNormalizeDate:
    def test_saint_theme_puts_year_last(self):
        assert normalize_date("08.20 2026") == "2026-08-20"

    def test_existing_two_part_format_unchanged(self):
        # "MM-DD" infers the year, so pin only the parts that don't drift.
        out = normalize_date("03-15")
        assert out.endswith("-03-15") and len(out) == 10

    def test_existing_three_part_format_unchanged(self):
        assert normalize_date("26-08-20") == "2026-08-20"

    def test_unrecognised_passes_through(self):
        assert normalize_date("garbage") == "garbage"


class TestParseArticleNo:
    def test_query_string_form_wins(self):
        assert parse_article_no("/bbs/board.php?bo_table=N4&wr_id=1234") == 1234

    def test_rewrite_form(self):
        assert parse_article_no("https://saint.skku.edu/05_03/473") == 473

    def test_rewrite_form_with_page_query(self):
        # The board number must not be mistaken for the article number, and
        # the trailing ?page=2 must not swallow the match.
        assert parse_article_no("https://saint.skku.edu/05_03/444?page=2") == 444

    def test_neither_form_returns_none(self):
        assert parse_article_no("/about") is None

    def test_wr_id_preferred_over_path_digits(self):
        assert parse_article_no("https://x.edu/05_03/999?bo_table=n&wr_id=7") == 7


class TestSaintTableSkin:
    async def test_rewrite_urls_yield_rows(self):
        """Before the fallback this returned [] — every row failed wr_id."""
        strategy = _make_strategy(SAINT_LIST_HTML)
        items = await strategy.crawl_list(SAINT_CONFIG, 0)

        assert [i.articleNo for i in items] == [473, 444]
        assert [i.date for i in items] == ["2026-08-20", "2026-08-11"]
        assert items[0].title == "논문제출자격시험 안내"

    async def test_missing_author_selector_is_not_fatal(self):
        """A board with no author column must still parse.

        selectors["author"] used to be a hard index, so the KeyError landed
        in the per-row except and cost the whole page.
        """
        strategy = _make_strategy(SAINT_LIST_HTML)
        items = await strategy.crawl_list(SAINT_CONFIG, 0)

        assert len(items) == 2
        assert all(i.author == "" for i in items)

    async def test_page_number_is_one_based_in_url(self):
        strategy = _make_strategy(SAINT_LIST_HTML)
        await strategy.crawl_list(SAINT_CONFIG, 1)
        url = strategy.fetcher.fetch.await_args[0][0]
        assert url == "https://saint.skku.edu/bbs/board.php?bo_table=05_03&page=2"


class TestOptionalAttachmentSelector:
    async def test_content_survives_when_attachments_are_not_collected(self):
        """Omitting detailAttachment must cost the attachments, not the post.

        A hard index here raised into crawl_detail's blanket except, which
        returns None — so a decision about attachments would have silently
        thrown away the article body too.
        """
        html = """
        <html><body>
          <div id="bo_v_con"><p>본문 내용</p></div>
          <section id="bo_v_file"><ul>
            <li><a class="view_file_download" href="/bbs/download.php?no=0">막힌첨부.hwp</a></li>
          </ul></section>
        </body></html>
        """
        strategy = _make_strategy(html)
        detail = await strategy.crawl_detail(
            {"articleNo": 473, "detailPath": "https://saint.skku.edu/05_03/473"},
            SAINT_CONFIG,
        )

        assert detail is not None
        assert detail.contentText == "본문 내용"
        assert detail.attachments == []
