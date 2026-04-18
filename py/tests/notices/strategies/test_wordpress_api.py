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


def _wpdm_block(slug: str, title: str, wpdmdl: int, refresh: str = "abc123") -> str:
    """Helper: generate a realistic WPDM card block matching cheme's DOM."""
    return (
        "<div class='w3eden'>"
        '<div class="link-template-default card mb-2"><div class="card-body">'
        '<div class="media">'
        '<div class="media-body">'
        f'<h3 class="package-title">'
        f"<a href='https://cheme.skku.edu/download/{slug}/'>{title}</a></h3>"
        "</div>"
        '<div class="ml-3">'
        '<a class="wpdm-download-link download-on-click btn btn-primary" '
        f"rel='nofollow' href='#' "
        f'data-downloadurl="https://cheme.skku.edu/download/{slug}/'
        f"?wpdmdl={wpdmdl}&amp;refresh={refresh}\">"
        "다운로드</a>"
        "</div></div></div></div></div>"
    )


def test_wordpress_api_wpdm_download_link():
    """WPDM: data-downloadurl에서 실제 다운로드 URL 추출, refresh 제거."""
    strategy = _make_strategy()
    html = _wpdm_block("some-slug", "출석·시험·성적처리에관한지침(2025.1.1.)", 18765)
    attachments = strategy._extract_attachments(html, "https://cheme.skku.edu")

    assert len(attachments) == 1
    assert attachments[0]["name"] == "출석·시험·성적처리에관한지침(2025.1.1.)"
    assert "wpdmdl=18765" in attachments[0]["url"]
    assert "refresh=" not in attachments[0]["url"]


def test_wordpress_api_wpdm_landing_page_not_captured():
    """WPDM 랜딩 페이지 URL (/download/slug/)은 첨부로 잡히지 않음."""
    strategy = _make_strategy()
    html = '<a href="https://cheme.skku.edu/download/some-slug/">파일 제목</a>'
    attachments = strategy._extract_attachments(html, "https://cheme.skku.edu")

    assert attachments == []


def test_wordpress_api_wpdm_multiple_attachments():
    """하나의 공지에 WPDM 첨부파일이 여러 개 있을 때 모두 추출."""
    strategy = _make_strategy()
    html = (
        "<p>공지 본문입니다.</p>"
        + _wpdm_block("file-a", "지침서.hwp", 100)
        + _wpdm_block("file-b", "별첨양식.zip", 200)
        + _wpdm_block("file-c", "참고자료.pdf", 300)
    )
    attachments = strategy._extract_attachments(html, "https://cheme.skku.edu")

    assert len(attachments) == 3
    names = {a["name"] for a in attachments}
    assert names == {"지침서.hwp", "별첨양식.zip", "참고자료.pdf"}
    for a in attachments:
        assert "wpdmdl=" in a["url"]
        assert "refresh=" not in a["url"]


def test_wordpress_api_mixed_wpdm_and_regular():
    """WPDM + 일반 파일 링크 공존 시 둘 다 추출, 중복 없음."""
    strategy = _make_strategy()
    html = (
        '<a href="https://cheme.skku.edu/wp-content/uploads/2026/04/form.hwp">신청서.hwp</a>'
        + _wpdm_block("slug", "지침서", 99)
    )
    attachments = strategy._extract_attachments(html, "https://cheme.skku.edu")

    assert len(attachments) == 2
    urls = {a["url"] for a in attachments}
    assert "https://cheme.skku.edu/wp-content/uploads/2026/04/form.hwp" in urls
    assert any("wpdmdl=99" in u for u in urls)


def test_wordpress_api_wpdm_no_false_positive_on_forms():
    """Google Forms 등 외부 링크는 첨부로 오인하지 않음."""
    strategy = _make_strategy()
    html = '<a href="https://forms.gle/sGQbCZ2KZ9gJ2FZs8">설문 참여</a>'
    attachments = strategy._extract_attachments(html, "https://cheme.skku.edu")

    assert attachments == []
