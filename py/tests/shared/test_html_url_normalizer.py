"""
Tests for shared.html_cleaner.normalize_content_urls.

Unlike `clean_html`, this helper preserves the raw HTML structure (style,
classes, all tags) and ONLY rewrites root-relative / relative `src` and
`href` attributes to absolute URLs. Used to repair the `content` field on
crawled notices so that downstream consumers (mobile app, server transform)
get image and link URLs that resolve.
"""
from __future__ import annotations

import pytest

from skkuverse_crawler.shared.html_cleaner import normalize_content_urls


BASE = "https://www.skku.edu/skku/campus/skk_comm/notice01.do"


class TestNormalizeContentUrls:
    def test_returns_none_for_none_input(self):
        assert normalize_content_urls(None, BASE) is None

    def test_returns_empty_for_empty_input(self):
        assert normalize_content_urls("", BASE) == ""

    def test_rewrites_relative_img_src_no_leading_slash(self):
        # Real SKKU pattern: src="_attach/image/2026/04/foo.jpg"
        html = '<p>본문</p><img alt="poster" src="_attach/image/2026/04/foo.jpg">'
        result = normalize_content_urls(html, BASE)
        assert 'src="https://www.skku.edu/skku/campus/skk_comm/_attach/image/2026/04/foo.jpg"' in result
        assert '<p>본문</p>' in result
        assert 'alt="poster"' in result

    def test_rewrites_root_relative_img_src(self):
        html = '<img src="/_attach/image/foo.jpg">'
        result = normalize_content_urls(html, BASE)
        assert 'src="https://www.skku.edu/_attach/image/foo.jpg"' in result

    def test_leaves_absolute_urls_alone(self):
        html = '<img src="https://www.skku.edu/static/foo.jpg">'
        result = normalize_content_urls(html, BASE)
        assert 'src="https://www.skku.edu/static/foo.jpg"' in result

    def test_leaves_protocol_relative_alone(self):
        # `//cdn.example.com/x.jpg` resolves against the BASE protocol via urljoin
        # → expected absolute URL with the base scheme
        html = '<img src="//cdn.example.com/x.jpg">'
        result = normalize_content_urls(html, BASE)
        assert 'src="https://cdn.example.com/x.jpg"' in result

    def test_leaves_data_uri_alone(self):
        html = '<img src="data:image/png;base64,iVBORw0KGgo=">'
        result = normalize_content_urls(html, BASE)
        assert 'data:image/png;base64' in result

    def test_rewrites_relative_anchor_href(self):
        html = '<a href="?mode=view&amp;articleNo=123">link</a>'
        result = normalize_content_urls(html, BASE)
        # urljoin on a query-only href against BASE → BASE + ?...
        assert 'href="https://www.skku.edu/skku/campus/skk_comm/notice01.do?mode=view' in result

    def test_leaves_mailto_and_tel_alone(self):
        html = '<a href="mailto:foo@bar.com">m</a><a href="tel:01012345678">t</a>'
        result = normalize_content_urls(html, BASE)
        assert 'href="mailto:foo@bar.com"' in result
        assert 'href="tel:01012345678"' in result

    def test_preserves_inline_styles_and_classes(self):
        html = '<div class="post-body" style="color:red"><img src="x.jpg" style="width:100%"></div>'
        result = normalize_content_urls(html, BASE)
        assert 'class="post-body"' in result
        assert 'style="color:red"' in result
        assert 'style="width:100%"' in result

    def test_handles_multiple_imgs_in_one_doc(self):
        html = (
            '<img src="a.jpg">'
            '<img src="/b.jpg">'
            '<img src="https://example.com/c.jpg">'
        )
        result = normalize_content_urls(html, BASE)
        assert 'src="https://www.skku.edu/skku/campus/skk_comm/a.jpg"' in result
        assert 'src="https://www.skku.edu/b.jpg"' in result
        assert 'src="https://example.com/c.jpg"' in result

    def test_does_not_rewrite_other_attribute_values(self):
        # Ensure we don't accidentally touch e.g. `data-src`, `srcset` aren't urljoined
        html = '<img src="a.jpg" data-src="b.jpg">'
        result = normalize_content_urls(html, BASE)
        # `src` rewritten
        assert 'src="https://www.skku.edu/skku/campus/skk_comm/a.jpg"' in result
        # `data-src` left alone
        assert 'data-src="b.jpg"' in result
