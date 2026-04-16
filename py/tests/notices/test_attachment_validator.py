from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from skkuverse_crawler.notices.attachment_validator import (
    AttachmentIssue,
    ValidationReport,
    check_reachability,
    validate_attachments,
    validate_duplicates,
    validate_host_allowed,
    validate_name,
    validate_name_is_url,
    validate_notice_attachments,
    validate_referer,
    validate_url_scheme,
)

# ---------------------------------------------------------------------------
# Sync: validate_url_scheme
# ---------------------------------------------------------------------------


class TestValidateUrlScheme:
    def test_valid_https(self):
        assert validate_url_scheme({"url": "https://skku.edu/f.pdf", "name": "f"}, 0) is None

    def test_valid_http(self):
        assert validate_url_scheme({"url": "http://bio.skku.edu/f.pdf", "name": "f"}, 0) is None

    def test_empty_url(self):
        issue = validate_url_scheme({"url": "", "name": "f"}, 0)
        assert issue is not None
        assert issue.check == "invalid_scheme"

    def test_anchor_only(self):
        issue = validate_url_scheme({"url": "#", "name": "f"}, 0)
        assert issue is not None
        assert issue.check == "invalid_scheme"

    def test_relative_path(self):
        issue = validate_url_scheme({"url": "/download/file.pdf", "name": "f"}, 0)
        assert issue is not None
        assert issue.check == "invalid_scheme"

    def test_missing_url_key(self):
        issue = validate_url_scheme({"name": "f"}, 0)
        assert issue is not None
        assert issue.check == "invalid_scheme"


# ---------------------------------------------------------------------------
# Sync: validate_name
# ---------------------------------------------------------------------------


class TestValidateName:
    def test_valid_name(self):
        assert validate_name({"url": "https://x.com/f", "name": "report.pdf"}, 0) is None

    def test_empty_name(self):
        issue = validate_name({"url": "https://x.com/f", "name": ""}, 0)
        assert issue is not None
        assert issue.check == "blank_name"

    def test_whitespace_name(self):
        issue = validate_name({"url": "https://x.com/f", "name": "   "}, 0)
        assert issue is not None
        assert issue.check == "blank_name"

    def test_unknown_name(self):
        issue = validate_name({"url": "https://x.com/f", "name": "Unknown"}, 0)
        assert issue is not None
        assert issue.check == "blank_name"

    def test_missing_name_key(self):
        issue = validate_name({"url": "https://x.com/f"}, 0)
        assert issue is not None
        assert issue.check == "blank_name"


# ---------------------------------------------------------------------------
# Sync: validate_name_is_url
# ---------------------------------------------------------------------------


class TestValidateNameIsUrl:
    def test_normal_name(self):
        assert validate_name_is_url({"url": "https://x.com/f", "name": "file.pdf"}, 0) is None

    def test_name_is_http_url(self):
        issue = validate_name_is_url({"url": "https://x.com/f", "name": "https://x.com/f"}, 0)
        assert issue is not None
        assert issue.check == "name_is_url"

    def test_name_is_http_no_s(self):
        issue = validate_name_is_url({"url": "http://x.com/f", "name": "http://x.com/f"}, 0)
        assert issue is not None
        assert issue.check == "name_is_url"


# ---------------------------------------------------------------------------
# Sync: validate_referer
# ---------------------------------------------------------------------------


class TestValidateReferer:
    def test_gnuboard_with_referer(self):
        att = {"url": "https://pharm.skku.edu/f", "name": "f", "referer": "https://pharm.skku.edu/board"}
        assert validate_referer(att, 0, "gnuboard") is None

    def test_gnuboard_missing_referer(self):
        att = {"url": "https://pharm.skku.edu/f", "name": "f"}
        issue = validate_referer(att, 0, "gnuboard")
        assert issue is not None
        assert issue.check == "missing_referer"

    def test_gnuboard_custom_missing_referer(self):
        issue = validate_referer({"url": "https://nano.skku.edu/f", "name": "f"}, 0, "gnuboard-custom")
        assert issue is not None
        assert issue.check == "missing_referer"

    def test_non_gnuboard_no_check(self):
        att = {"url": "https://skku.edu/f", "name": "f"}
        assert validate_referer(att, 0, "skku-standard") is None

    def test_none_strategy_no_check(self):
        att = {"url": "https://skku.edu/f", "name": "f"}
        assert validate_referer(att, 0, None) is None


# ---------------------------------------------------------------------------
# Sync: validate_host_allowed
# ---------------------------------------------------------------------------


class TestValidateHostAllowed:
    def test_skku_edu(self):
        assert validate_host_allowed({"url": "https://www.skku.edu/f.pdf", "name": "f"}, 0) is None

    def test_subdomain_skku_edu(self):
        assert validate_host_allowed({"url": "https://pharm.skku.edu/f", "name": "f"}, 0) is None

    def test_skkumed(self):
        assert validate_host_allowed({"url": "https://www.skkumed.ac.kr/f", "name": "f"}, 0) is None

    def test_disallowed_host(self):
        issue = validate_host_allowed({"url": "https://evil.com/f", "name": "f"}, 0)
        assert issue is not None
        assert issue.check == "disallowed_host"

    def test_relative_url_skipped(self):
        # Scheme check handles this; host check should not double-flag
        assert validate_host_allowed({"url": "/relative/path", "name": "f"}, 0) is None


# ---------------------------------------------------------------------------
# Sync: validate_duplicates
# ---------------------------------------------------------------------------


class TestValidateDuplicates:
    def test_no_duplicates(self):
        atts = [
            {"url": "https://a.skku.edu/1", "name": "a"},
            {"url": "https://a.skku.edu/2", "name": "b"},
        ]
        assert validate_duplicates(atts) == []

    def test_duplicate_url(self):
        atts = [
            {"url": "https://a.skku.edu/1", "name": "a"},
            {"url": "https://a.skku.edu/1", "name": "b"},
        ]
        issues = validate_duplicates(atts)
        assert len(issues) == 1
        assert issues[0].check == "duplicate_url"
        assert issues[0].attachment_index == 1

    def test_triple_duplicate(self):
        atts = [
            {"url": "https://a.skku.edu/1", "name": "a"},
            {"url": "https://a.skku.edu/1", "name": "b"},
            {"url": "https://a.skku.edu/1", "name": "c"},
        ]
        issues = validate_duplicates(atts)
        assert len(issues) == 2
        assert issues[0].attachment_index == 1
        assert issues[1].attachment_index == 2


# ---------------------------------------------------------------------------
# Sync: validate_notice_attachments (orchestrator)
# ---------------------------------------------------------------------------


class TestValidateNoticeAttachments:
    def test_clean_notice(self):
        atts = [{"url": "https://www.skku.edu/file.pdf", "name": "report.pdf"}]
        assert validate_notice_attachments(atts, "skku-standard") == []

    def test_multiple_issues(self):
        atts = [
            {"url": "", "name": ""},  # invalid_scheme + blank_name
            {"url": "https://evil.com/x", "name": "ok.pdf"},  # disallowed_host
        ]
        issues = validate_notice_attachments(atts, "skku-standard")
        checks = {i.check for i in issues}
        assert "invalid_scheme" in checks
        assert "blank_name" in checks
        assert "disallowed_host" in checks

    def test_gnuboard_referer_check(self):
        atts = [{"url": "https://pharm.skku.edu/bbs/download.php?no=1", "name": "f.pdf"}]
        issues = validate_notice_attachments(atts, "gnuboard")
        assert any(i.check == "missing_referer" for i in issues)


# ---------------------------------------------------------------------------
# Async: check_reachability
# ---------------------------------------------------------------------------

import asyncio


class TestCheckReachability:
    @respx.mock
    async def test_reachable_200(self):
        respx.head("https://www.skku.edu/f.pdf").mock(return_value=httpx.Response(200))
        sem = asyncio.Semaphore(5)
        async with httpx.AsyncClient() as client:
            issue = await check_reachability("https://www.skku.edu/f.pdf", "https://skku.edu", client, sem, 0, "f.pdf")
        assert issue is None

    @respx.mock
    async def test_unreachable_404(self):
        respx.head("https://www.skku.edu/f.pdf").mock(return_value=httpx.Response(404))
        sem = asyncio.Semaphore(5)
        async with httpx.AsyncClient() as client:
            issue = await check_reachability("https://www.skku.edu/f.pdf", "https://skku.edu", client, sem, 0, "f.pdf")
        assert issue is not None
        assert issue.check == "unreachable"
        assert "404" in issue.detail

    @respx.mock
    async def test_unreachable_timeout(self):
        respx.head("https://www.skku.edu/f.pdf").mock(side_effect=httpx.ConnectTimeout("timeout"))
        sem = asyncio.Semaphore(5)
        async with httpx.AsyncClient() as client:
            issue = await check_reachability("https://www.skku.edu/f.pdf", "https://skku.edu", client, sem, 0, "f.pdf")
        assert issue is not None
        assert issue.check == "unreachable"
        assert "timeout" in issue.detail.lower()

    @respx.mock
    async def test_unreachable_connection_error(self):
        respx.head("https://www.skku.edu/f.pdf").mock(side_effect=httpx.ConnectError("refused"))
        sem = asyncio.Semaphore(5)
        async with httpx.AsyncClient() as client:
            issue = await check_reachability("https://www.skku.edu/f.pdf", "https://skku.edu", client, sem, 0, "f.pdf")
        assert issue is not None
        assert issue.check == "unreachable"


# ---------------------------------------------------------------------------
# Async: validate_attachments (full pipeline with mock DB)
# ---------------------------------------------------------------------------


class TestValidateAttachmentsPipeline:
    async def test_full_pipeline(self, mock_collection):
        """End-to-end with mock DB, HTTP disabled."""
        from bson import ObjectId

        docs = [
            {
                "_id": ObjectId(),
                "articleNo": 100,
                "sourceDeptId": "skku-main",
                "sourceUrl": "https://www.skku.edu/skku/campus/skku_news.do?mode=view&articleNo=100",
                "attachments": [
                    {"url": "https://www.skku.edu/file.pdf", "name": "report.pdf"},
                    {"url": "", "name": ""},  # two issues
                ],
            },
        ]

        # Mock the async cursor
        async def mock_cursor_iter(self):
            for doc in docs:
                yield doc

        cursor_mock = AsyncMock()
        cursor_mock.limit = lambda n: cursor_mock
        cursor_mock.__aiter__ = mock_cursor_iter
        mock_collection.find = lambda *a, **kw: cursor_mock

        dept_data = [
            {"id": "skku-main", "strategy": "skku-standard"},
        ]

        with patch(
            "skkuverse_crawler.notices.config.loader.load_and_validate",
            return_value=dept_data,
        ):
            report = await validate_attachments(check_http=False)

        assert isinstance(report, ValidationReport)
        assert report.total_notices == 1
        assert report.total_attachments == 2
        assert report.notices_with_issues == 1
        assert "invalid_scheme" in report.issue_counts
        assert "blank_name" in report.issue_counts

    async def test_gnuboard_skips_http(self, mock_collection):
        """Gnuboard departments should increment skipped_http_checks."""
        from bson import ObjectId

        docs = [
            {
                "_id": ObjectId(),
                "articleNo": 200,
                "sourceDeptId": "pharm",
                "sourceUrl": "https://pharm.skku.edu/bbs/board.php?bo_table=notice&wr_id=200",
                "attachments": [
                    {
                        "url": "https://pharm.skku.edu/bbs/download.php?no=1",
                        "name": "file.hwp",
                        "referer": "https://pharm.skku.edu/bbs/board.php?bo_table=notice&wr_id=200",
                    },
                ],
            },
        ]

        async def mock_cursor_iter(self):
            for doc in docs:
                yield doc

        cursor_mock = AsyncMock()
        cursor_mock.limit = lambda n: cursor_mock
        cursor_mock.__aiter__ = mock_cursor_iter
        mock_collection.find = lambda *a, **kw: cursor_mock

        dept_data = [
            {"id": "pharm", "strategy": "gnuboard"},
        ]

        with patch(
            "skkuverse_crawler.notices.config.loader.load_and_validate",
            return_value=dept_data,
        ):
            report = await validate_attachments(check_http=True)

        assert report.skipped_http_checks == 1
        assert report.notices_with_issues == 0  # referer present, all valid

    async def test_unknown_dept_treated_as_non_gnuboard(self, mock_collection):
        """Unknown sourceDeptId should not crash; no referer check."""
        from bson import ObjectId

        docs = [
            {
                "_id": ObjectId(),
                "articleNo": 300,
                "sourceDeptId": "deleted-dept",
                "sourceUrl": "https://www.skku.edu/deleted",
                "attachments": [
                    {"url": "https://www.skku.edu/file.pdf", "name": "ok.pdf"},
                ],
            },
        ]

        async def mock_cursor_iter(self):
            for doc in docs:
                yield doc

        cursor_mock = AsyncMock()
        cursor_mock.limit = lambda n: cursor_mock
        cursor_mock.__aiter__ = mock_cursor_iter
        mock_collection.find = lambda *a, **kw: cursor_mock

        with patch(
            "skkuverse_crawler.notices.config.loader.load_and_validate",
            return_value=[],  # empty — dept not found
        ):
            report = await validate_attachments(check_http=False)

        assert report.total_notices == 1
        assert report.notices_with_issues == 0  # no issues; no referer check for unknown
