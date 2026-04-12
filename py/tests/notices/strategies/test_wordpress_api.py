from __future__ import annotations

from unittest.mock import AsyncMock

from skkuverse_crawler.notices.strategies.wordpress_api import WordPressApiStrategy


def _make_strategy() -> WordPressApiStrategy:
    return WordPressApiStrategy(AsyncMock())


def test_wordpress_api_image_attachment_by_uploads_path():
    strategy = _make_strategy()
    html = (
        '<p>공고 이미지입니다.</p>'
        '<a href="https://cheme.skku.edu/wp-content/uploads/2026/04/notice.jpg">공고.jpg</a>'
    )
    attachments = strategy._extract_attachments(html, "https://cheme.skku.edu")

    assert len(attachments) == 1
    assert attachments[0]["name"] == "공고.jpg"
    assert attachments[0]["url"] == "https://cheme.skku.edu/wp-content/uploads/2026/04/notice.jpg"


def test_wordpress_api_doc_still_works():
    """회귀: 기존 pdf/hwp 추출 동작 유지."""
    strategy = _make_strategy()
    html = (
        '<a href="https://cheme.skku.edu/wp-content/uploads/2026/04/form.hwp">신청서.hwp</a>'
        '<a href="/docs/notice.pdf">공고.pdf</a>'
    )
    attachments = strategy._extract_attachments(html, "https://cheme.skku.edu")

    urls = {a["url"] for a in attachments}
    assert "https://cheme.skku.edu/wp-content/uploads/2026/04/form.hwp" in urls
    assert "https://cheme.skku.edu/docs/notice.pdf" in urls


def test_wordpress_api_ignores_plain_page_links():
    """일반 페이지 링크는 첨부로 오인하지 않음."""
    strategy = _make_strategy()
    html = (
        '<a href="https://cheme.skku.edu/about">학과 소개</a>'
        '<a href="/category/notice">공지 목록</a>'
    )
    attachments = strategy._extract_attachments(html, "https://cheme.skku.edu")

    assert attachments == []


def test_wordpress_api_extended_media_extensions():
    """확장된 미디어/텍스트 확장자도 캐치."""
    strategy = _make_strategy()
    html = (
        '<a href="/files/report.txt">보고서.txt</a>'
        '<a href="/files/video.mp4">영상.mp4</a>'
    )
    attachments = strategy._extract_attachments(html, "https://cheme.skku.edu")

    assert len(attachments) == 2


def test_wordpress_api_wpdm_download_link():
    """WPDM(WordPress Download Manager) /download/slug/ 패턴 추출."""
    strategy = _make_strategy()
    html = (
        '<a href="https://cheme.skku.edu/download/'
        '%ec%b6%9c%ec%84%9d%c2%b7%ec%8b%9c%ed%97%98%c2%b7'
        '%ec%84%b1%ec%a0%81%ec%b2%98%eb%a6%ac%ec%97%90%ea%b4%80%ed%95%9c'
        '%ec%a7%80%ec%b9%a82025-1-1/">'
        '출석·시험·성적처리에관한지침(2025.1.1.)</a>'
    )
    attachments = strategy._extract_attachments(html, "https://cheme.skku.edu")

    assert len(attachments) == 1
    assert attachments[0]["name"] == "출석·시험·성적처리에관한지침(2025.1.1.)"


def test_wordpress_api_wpdm_no_false_positive_on_forms():
    """Google Forms 등 외부 링크는 WPDM 패턴에 걸리지 않음."""
    strategy = _make_strategy()
    html = '<a href="https://forms.gle/sGQbCZ2KZ9gJ2FZs8">설문 참여</a>'
    attachments = strategy._extract_attachments(html, "https://cheme.skku.edu")

    assert attachments == []
