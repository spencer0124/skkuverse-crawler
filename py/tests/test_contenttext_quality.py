"""contentText 품질 개선 검증 — 105건 QA 실패 케이스 재현."""

import sys
from unittest.mock import patch

import pytest

from skkuverse_crawler.notices.normalizer import _text_from_clean_html, build_notice
from skkuverse_crawler.notices.models import NoticeListItem, NoticeDetail
from skkuverse_crawler.shared.html_cleaner import clean_html


# ── _text_from_clean_html 단위 테스트 ──


class TestTextFromCleanHtml:
    """cleanHtml → plain text 변환 품질."""

    def test_table_content_preserved(self):
        """Case 4/5: 화재대피 훈련 — HTML 테이블 안의 날짜가 추출되어야 함."""
        html = """
        <p>기숙사에서는 화재 발생 시 훈련을 실시합니다.</p>
        <p>1. 훈련 일정 및 장소</p>
        <table>
          <thead><tr><th>일정</th><th>시간</th><th>장소</th></tr></thead>
          <tbody>
            <tr><td>4월 14일(화)</td><td>19:00</td><td>의관</td></tr>
            <tr><td>4월 15일(수)</td><td>19:00</td><td>예관</td></tr>
            <tr><td>4월 16일(목)</td><td>19:00</td><td>인관</td></tr>
          </tbody>
        </table>
        """
        text = _text_from_clean_html(html)
        assert "4월 14일" in text
        assert "4월 15일" in text
        assert "4월 16일" in text
        assert "19:00" in text
        assert "의관" in text

    def test_table_cells_not_concatenated(self):
        """테이블 셀 사이에 공백이 있어야 함 (붙으면 안 됨)."""
        html = "<table><tr><td>3월 30일</td><td>4월 13일</td></tr></table>"
        text = _text_from_clean_html(html)
        # "3월 30일4월 13일"이 아니라 분리되어야 함
        assert "3월 30일" in text
        assert "4월 13일" in text
        assert "3월 30일4월" not in text

    def test_nav_text_absent(self):
        """cleanHtml에는 nav가 이미 제거되어 있으므로 nav 텍스트 없어야 함."""
        # cleanHtml은 html_cleaner가 .board-view-nav를 제거한 결과
        html = "<p>본문 내용입니다.</p>"
        text = _text_from_clean_html(html)
        assert "이전글" not in text
        assert "다음글" not in text
        assert "본문 내용입니다" in text

    def test_empty_html(self):
        """빈 HTML → 빈 문자열."""
        assert _text_from_clean_html("<p></p>") == ""


# ── clean_html 파이프라인 통합 테스트 ──


class TestCleanHtmlNavRemoval:
    """clean_html이 네비게이션을 제거하는지 확인."""

    def test_board_view_nav_removed(self):
        """Case 7: 삼성E&A — .board-view-nav 클래스가 있으면 제거."""
        raw = """
        <div class="board-view-content">
            <p>삼성E&A 3급 신입사원을 모집합니다. 접수기간: 3/10~3/20</p>
        </div>
        <div class="board-view-nav">
            <a href="?mode=view&articleNo=100">이전글 롯데케미칼 채용</a>
            <a href="?mode=view&articleNo=102">다음글 삼성물산 채용</a>
            <a href="?mode=list">목록</a>
        </div>
        """
        cleaned = clean_html(raw, "https://example.com")
        assert cleaned is not None
        text = _text_from_clean_html(cleaned)
        assert "삼성E&A" in text or "삼성E" in text
        assert "접수기간" in text
        assert "이전글" not in text
        assert "다음글" not in text
        assert "목록" not in text

    def test_mode_list_link_removed(self):
        """a[href*='mode=list'] 셀렉터로 목록 링크 제거."""
        raw = """
        <p>본문입니다.</p>
        <a href="?mode=list">목록</a>
        """
        cleaned = clean_html(raw, "https://example.com")
        assert cleaned is not None
        text = _text_from_clean_html(cleaned)
        assert "본문입니다" in text
        assert "목록" not in text


# ── build_notice 통합 테스트 ──


class TestBuildNoticeContentText:
    """build_notice가 cleanHtml에서 contentText를 파생하는지."""

    def _make_list_item(self):
        return NoticeListItem(
            articleNo=1,
            title="테스트",
            category="",
            author="관리자",
            date="2026-04-01",
            views=0,
            detailPath="?mode=view&articleNo=1",
        )

    def test_contenttext_from_cleanhtml_not_raw(self):
        """cleanHtml이 있으면 raw contentText 대신 cleanHtml 파생 텍스트 사용."""
        raw_html = """
        <div>
            <p>본문 내용</p>
            <table><tr><td>4월 14일</td><td>19:00</td></tr></table>
        </div>
        <div class="board-view-nav">
            <a href="?mode=list">목록</a>
            이전글 다음글
        </div>
        """
        detail = NoticeDetail(
            content=raw_html,
            contentText="본문 내용4월 14일19:00목록이전글 다음글",  # raw .get_text()
        )
        notice = build_notice(
            self._make_list_item(),
            detail,
            department="test",
            source_dept_id="test",
            base_url="https://example.com",
        )
        # cleanHtml 파생이므로 nav 없고 테이블 내용 있어야 함
        assert "본문 내용" in notice.contentText
        assert "4월 14일" in notice.contentText
        assert "이전글" not in notice.contentText
        assert "다음글" not in notice.contentText
        assert "목록" not in notice.contentText

    def test_fallback_to_raw_when_no_cleanhtml(self):
        """cleanHtml이 None이면 raw contentText 사용."""
        detail = NoticeDetail(
            content="",  # empty → cleanHtml will be None
            contentText="이전글 다음글 본문",
        )
        notice = build_notice(
            self._make_list_item(),
            detail,
            department="test",
            source_dept_id="test",
            base_url="https://example.com",
        )
        # fallback이므로 raw 그대로
        assert notice.contentText == "이전글 다음글 본문"

    def test_no_detail(self):
        """detail이 None이면 contentText도 None."""
        notice = build_notice(
            self._make_list_item(),
            None,
            department="test",
            source_dept_id="test",
            base_url="https://example.com",
        )
        assert notice.contentText is None
