"""Unit tests for ``markdown_validator``."""
from __future__ import annotations

from unittest.mock import AsyncMock

from skkuverse_crawler.notices.markdown_validator import (
    MarkdownValidationReport,
    check_broken_link,
    check_cross_line_strong,
    check_empty_table_header,
    check_space_before_close_emphasis,
    validate_markdown,
    validate_notice_markdown,
)


# ── check_cross_line_strong ───────────────────────────


class TestCrossLineStrong:
    def test_single_line_bold_ok(self):
        assert check_cross_line_strong("**hello world**") == []

    def test_single_newline_detected(self):
        md = "**변경 후 강의실:\n85718호**"
        issues = check_cross_line_strong(md)
        assert len(issues) == 1
        assert issues[0].check == "cross_line_strong"
        assert issues[0].severity == "warning"
        assert issues[0].line == 1

    def test_multi_newline_detected(self):
        md = "**라벨\n\n값**"
        issues = check_cross_line_strong(md)
        assert len(issues) == 1
        assert "2 line(s)" in issues[0].detail

    def test_two_separate_strongs_not_flagged(self):
        """**A**\\n**B** should NOT match — critical false-positive guard."""
        md = "**First**\n**Second**"
        issues = check_cross_line_strong(md)
        assert issues == []

    def test_strong_with_inner_single_asterisk(self):
        """** containing single * should match cross-line, not stop early."""
        md = "**label *emphasized*\nvalue**"
        issues = check_cross_line_strong(md)
        assert len(issues) == 1

    def test_closing_then_opening_on_next_line_not_flagged(self):
        """**A:** text\\n\\n**B:** text — two separate bolds, NOT cross-line."""
        md = "**신청 기간:** 4월 1일\n\n**★ 워크숍 안내**"
        assert check_cross_line_strong(md) == []

    def test_closing_paren_bold_then_opening_bold_not_flagged(self):
        """(**A**) then (**B**) on separate lines — NOT cross-line."""
        md = "(**계속장학생도 포함**)\n\n(**단, 매학기 신청기간 내 서류 제출 필수**)"
        assert check_cross_line_strong(md) == []


# ── check_space_before_close_emphasis ─────────────────


class TestSpaceBeforeCloseEmphasis:
    def test_normal_bold_ok(self):
        assert check_space_before_close_emphasis("**접수 기한:**") == []

    def test_space_before_close_detected(self):
        md = "**가. 접수 기한: **"
        issues = check_space_before_close_emphasis(md)
        assert len(issues) == 1
        assert issues[0].check == "space_before_close_emphasis"
        assert issues[0].severity == "error"

    def test_tab_before_close_detected(self):
        md = "**text\t**"
        issues = check_space_before_close_emphasis(md)
        assert len(issues) == 1

    def test_closing_then_opening_with_space_not_flagged(self):
        """**A**로 **B** — two separate bolds with Korean particle, NOT space-before-close."""
        md = "**이수자**로 **총 평점**"
        assert check_space_before_close_emphasis(md) == []

    def test_closing_then_opening_long_gap_not_flagged(self):
        """**A**에 초청되며, 결선 진출 팀에게는 **B** — long text between bolds."""
        md = "**결선 라운드**에 초청되며, 결선 진출 팀에게는 **3박 숙박이 제공**"
        assert check_space_before_close_emphasis(md) == []

    def test_start_of_string_still_detected(self):
        """**A ** at start of string — pos==0, no preceding char, must flag."""
        md = "**A **"
        issues = check_space_before_close_emphasis(md)
        assert len(issues) == 1

    def test_after_newline_still_detected(self):
        """**A ** after newline — preceded by whitespace, must flag."""
        md = "text\n**A **"
        issues = check_space_before_close_emphasis(md)
        assert len(issues) == 1

    def test_consecutive_bolds_not_flagged(self):
        """**A** **B** **C** — multiple separate bolds, no FP."""
        md = "**A** **B** **C**"
        assert check_space_before_close_emphasis(md) == []

    def test_hangul_before_opening_not_flagged(self):
        """가**A ** — preceded by Hangul character, closing not opening."""
        md = "가**A **"
        assert check_space_before_close_emphasis(md) == []


# ── check_empty_table_header ─────────────────────────


class TestEmptyTableHeader:
    def test_normal_table_ok(self):
        md = "| A | B |\n| --- | --- |\n| 1 | 2 |"
        assert check_empty_table_header(md) == []

    def test_empty_header_detected(self):
        md = "|  |  |  |\n| --- | --- | --- |\n| 직종 | 담당업무 | 분야 |"
        issues = check_empty_table_header(md)
        assert len(issues) == 1
        assert issues[0].check == "empty_table_header"
        assert issues[0].severity == "warning"

    def test_partially_filled_header_ok(self):
        md = "| A |  |\n| --- | --- |\n| 1 | 2 |"
        assert check_empty_table_header(md) == []


# ── check_broken_link ────────────────────────────────


class TestBrokenLink:
    def test_valid_link_ok(self):
        assert check_broken_link("[text](https://skku.edu)") == []

    def test_unclosed_paren_detected(self):
        md = "[text](https://skku.edu"
        issues = check_broken_link(md)
        assert len(issues) == 1
        assert issues[0].check == "broken_link"
        assert issues[0].severity == "error"

    def test_image_unclosed_detected(self):
        md = "![alt](https://skku.edu/img.png"
        issues = check_broken_link(md)
        assert len(issues) == 1


# ── validate_notice_markdown ─────────────────────────


class TestValidateNoticeMarkdown:
    def test_clean_markdown_returns_empty(self):
        md = "Hello **world**\n\nParagraph 2."
        assert validate_notice_markdown(md) == []

    def test_multiple_issue_types(self):
        md = "**broken\nbold** and **trailing **"
        issues = validate_notice_markdown(md)
        checks = {i.check for i in issues}
        assert "cross_line_strong" in checks
        assert "space_before_close_emphasis" in checks

    def test_min_severity_filters_warnings(self):
        md = "**broken\nbold**"
        all_issues = validate_notice_markdown(md, min_severity="warning")
        error_only = validate_notice_markdown(md, min_severity="error")
        assert len(all_issues) == 1
        assert all_issues[0].severity == "warning"
        assert error_only == []

    def test_empty_markdown_returns_empty(self):
        assert validate_notice_markdown("") == []
        assert validate_notice_markdown("   ") == []

    def test_none_like_empty(self):
        # None is handled by the caller (DB orchestrator), but empty string
        # should not raise
        assert validate_notice_markdown("") == []

    def test_crlf_normalized(self):
        md = "**broken\r\nbold**"
        issues = validate_notice_markdown(md)
        assert len(issues) == 1
        assert issues[0].check == "cross_line_strong"


# ── validate_markdown (async pipeline) ───────────────


class TestValidateMarkdownPipeline:
    async def test_pipeline_detects_issues(self, mock_collection):
        from bson import ObjectId

        docs = [
            {
                "_id": ObjectId(),
                "articleNo": 1,
                "sourceDeptId": "cse-undergrad",
                "sourceUrl": "https://cse.skku.edu/notice/1",
                "cleanMarkdown": "**broken\nbold**",
            },
            {
                "_id": ObjectId(),
                "articleNo": 2,
                "sourceDeptId": "cse-undergrad",
                "sourceUrl": "https://cse.skku.edu/notice/2",
                "cleanMarkdown": "Clean **text** here.",
            },
        ]
        it = iter(docs)

        async def mock_cursor_iter(self):
            for doc in it:
                yield doc

        cursor_mock = AsyncMock()
        cursor_mock.limit = lambda n: cursor_mock
        cursor_mock.__aiter__ = mock_cursor_iter
        mock_collection.find = lambda *a, **kw: cursor_mock

        report = await validate_markdown(dept_filter=("cse-undergrad",), limit=10)

        assert isinstance(report, MarkdownValidationReport)
        assert report.total_notices == 2
        assert report.notices_with_issues == 1
        assert report.issue_counts.get("cross_line_strong", 0) == 1

    async def test_empty_markdown_skipped(self, mock_collection):
        from bson import ObjectId

        docs = [
            {
                "_id": ObjectId(),
                "articleNo": 3,
                "sourceDeptId": "test",
                "sourceUrl": "",
                "cleanMarkdown": "",
            },
        ]
        it = iter(docs)

        async def mock_cursor_iter(self):
            for doc in it:
                yield doc

        cursor_mock = AsyncMock()
        cursor_mock.limit = lambda n: cursor_mock
        cursor_mock.__aiter__ = mock_cursor_iter
        mock_collection.find = lambda *a, **kw: cursor_mock

        report = await validate_markdown()

        assert report.total_notices == 1
        assert report.notices_with_issues == 0
