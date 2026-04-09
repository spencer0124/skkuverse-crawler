from __future__ import annotations

from skkuverse_crawler.notices.hashing import compute_content_hash


class TestComputeContentHash:
    def test_none_returns_none(self):
        assert compute_content_hash(None) is None

    def test_empty_string_returns_none(self):
        # Spec: falsy input → None (빈 본문에 hash 달아봐야 의미 없음)
        assert compute_content_hash("") is None

    def test_determinism(self):
        html = "<p>공지사항 내용입니다.</p>"
        assert compute_content_hash(html) == compute_content_hash(html)

    def test_different_input_different_hash(self):
        h1 = compute_content_hash("<p>A</p>")
        h2 = compute_content_hash("<p>B</p>")
        assert h1 != h2

    def test_whitespace_difference_matters(self):
        h1 = compute_content_hash("<p>hello</p>")
        h2 = compute_content_hash("<p> hello</p>")
        assert h1 != h2

    def test_korean_utf8(self):
        result = compute_content_hash("<p>성균관대학교 공지</p>")
        assert result is not None
        assert len(result) == 64  # SHA-256 hex digest

    def test_returns_sha256_hex(self):
        result = compute_content_hash("<p>test</p>")
        assert result is not None
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)
