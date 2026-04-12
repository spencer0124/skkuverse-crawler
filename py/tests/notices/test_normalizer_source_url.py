"""Tests for sourceUrl construction in normalizer.build_notice.

Covers the three branches in build_notice's sourceUrl logic:
  1. detailPath starts with "http" → passthrough
  2. detailPath starts with "?"     → base_url + detailPath
  3. otherwise (relative path)      → urljoin(base_url, detailPath)
"""

from __future__ import annotations

import pytest

from skkuverse_crawler.notices.normalizer import _inject_image_dimensions, build_notice
from skkuverse_crawler.notices.models import NoticeDetail, NoticeListItem


def _item(*, detail_path: str, article_no: int = 1) -> NoticeListItem:
    return NoticeListItem(
        articleNo=article_no,
        title="test",
        category="",
        author="",
        date="2026-01-01",
        views=0,
        detailPath=detail_path,
    )


_DETAIL = NoticeDetail(content="<p>body</p>", contentText="body", attachments=[])


class TestSourceUrl:
    """sourceUrl resolution for each detailPath format."""

    def test_absolute_url_passthrough(self):
        """Branch 1: detailPath starting with http is used as-is."""
        notice = build_notice(
            _item(detail_path="https://example.com/notice/123"),
            _DETAIL,
            department="test",
            source_dept_id="test",
            base_url="https://other.com/board.php",
        )
        assert notice.sourceUrl == "https://example.com/notice/123"

    def test_query_string_appended_to_base(self):
        """Branch 2: detailPath starting with ? is appended to base_url (skku-standard)."""
        notice = build_notice(
            _item(detail_path="?mode=view&articleNo=136184"),
            _DETAIL,
            department="학부통합",
            source_dept_id="skku-main",
            base_url="https://www.skku.edu/skku/campus/skk_comm/notice01.do",
        )
        assert notice.sourceUrl == (
            "https://www.skku.edu/skku/campus/skk_comm/notice01.do"
            "?mode=view&articleNo=136184"
        )

    def test_relative_path_nano(self):
        """Branch 3: gnuboard-custom detailPath resolved via urljoin (nano)."""
        notice = build_notice(
            _item(
                detail_path="board.php?tbl=bbs42&mode=VIEW&num=427",
                article_no=427,
            ),
            _DETAIL,
            department="나노공학과",
            source_dept_id="nano",
            base_url="https://nano.skku.edu/bbs/board.php",
        )
        assert notice.sourceUrl == (
            "https://nano.skku.edu/bbs/board.php?tbl=bbs42&mode=VIEW&num=427"
        )

    def test_relative_path_medicine(self):
        """Branch 3: skkumed-asp detailPath — different filename in same directory."""
        notice = build_notice(
            _item(
                detail_path="community_notice_w.asp?bcode=nt&number=4665",
                article_no=4665,
            ),
            _DETAIL,
            department="의과대학",
            source_dept_id="medicine",
            base_url="https://www.skkumed.ac.kr/community_notice.asp",
        )
        assert notice.sourceUrl == (
            "https://www.skkumed.ac.kr/community_notice_w.asp?bcode=nt&number=4665"
        )

    @pytest.mark.parametrize(
        "detail_path",
        ["", " "],
        ids=["empty", "whitespace"],
    )
    def test_empty_detail_path_uses_base_url(self, detail_path: str):
        """Empty/whitespace detailPath falls through to urljoin, which returns base_url."""
        notice = build_notice(
            _item(detail_path=detail_path),
            _DETAIL,
            department="test",
            source_dept_id="test",
            base_url="https://example.com/board.php",
        )
        # urljoin("https://example.com/board.php", "") → "https://example.com/board.php"
        assert notice.sourceUrl.startswith("https://example.com/")


# ── Image dimension injection ─────────────────────────


class TestInjectImageDimensions:
    def test_injects_width_height(self):
        html = '<img src="https://example.com/a.png" alt="pic"/>'
        dims = {"https://example.com/a.png": (800, 600)}
        result = _inject_image_dimensions(html, dims)
        assert 'width="800"' in result
        assert 'height="600"' in result

    def test_preserves_existing_dimensions(self):
        html = '<img src="https://example.com/a.png" width="100" height="50"/>'
        dims = {"https://example.com/a.png": (800, 600)}
        result = _inject_image_dimensions(html, dims)
        assert 'width="100"' in result
        assert 'height="50"' in result

    def test_no_match_returns_unchanged(self):
        html = '<img src="https://example.com/a.png"/>'
        dims = {"https://example.com/other.png": (800, 600)}
        result = _inject_image_dimensions(html, dims)
        assert "width" not in result

    def test_empty_dimensions_returns_unchanged(self):
        html = '<img src="https://example.com/a.png"/>'
        result = _inject_image_dimensions(html, {})
        assert result == html

    def test_build_notice_passes_dimensions_to_cleanhtml(self):
        detail = NoticeDetail(
            content='<p><img src="https://example.com/a.png"/></p>',
            contentText="",
        )
        notice = build_notice(
            _item(detail_path="?articleNo=1"),
            detail,
            department="test",
            source_dept_id="test",
            base_url="https://example.com/",
            image_dimensions={"https://example.com/a.png": (400, 300)},
        )
        assert notice.cleanHtml is not None
        assert 'width="400"' in notice.cleanHtml
        assert 'height="300"' in notice.cleanHtml
        # cleanMarkdown should contain dimension hint
        assert notice.cleanMarkdown is not None
        assert "(400x300)" in notice.cleanMarkdown
