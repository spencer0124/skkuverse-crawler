"""Content pipeline stages — the invariants the goldens can't see.

The goldens prove the emit path is byte-identical end to end; these pin
the properties that only show up on inputs the fixtures don't contain
(oversized bodies, images) plus the equality of build_notice's two paths.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from skkuverse_crawler.core.pipeline import ContentDoc, StageContext
from skkuverse_crawler.modules.notices.image_verifier import ImageCheckResult
from skkuverse_crawler.modules.notices.models import NoticeDetail, NoticeListItem
from skkuverse_crawler.modules.notices.normalizer import MAX_CONTENT_BYTES, build_notice
from skkuverse_crawler.modules.notices.stages import (
    DEFAULT_PIPELINE,
    CleanHtml,
    ContentHash,
    ExtractText,
    InjectImageDimensions,
    NormalizeUrls,
    SizeGuard,
    ToMarkdown,
    VerifyImages,
)

BASE_URL = "https://example.ac.kr/board"


def _ctx(**kwargs) -> StageContext:
    return StageContext(
        source_id="test-dept", base_url=BASE_URL, source_url=f"{BASE_URL}?no=1", **kwargs
    )


class TestFanOut:
    """clean_html and content are siblings, both derived from raw."""

    async def test_clean_html_derives_from_raw_not_from_content(self):
        raw = '<p><img src="/img/a.png"></p>'
        doc = ContentDoc(raw=raw)
        doc = await NormalizeUrls().apply(doc, _ctx())
        # Poison the sibling slot: a chained CleanHtml would consume it.
        doc.content = "<p>POISONED</p>"
        doc = await CleanHtml().apply(doc, _ctx())
        assert "POISONED" not in (doc.clean_html or "")

    async def test_stage_order_of_default_pipeline(self):
        assert [s.name for s in DEFAULT_PIPELINE.stages] == [
            "normalize-urls",
            "clean-html",
            "verify-images",
            "inject-image-dimensions",
            "size-guard",
            "extract-text",
            "to-markdown",
            "content-hash",
        ]

    async def test_empty_raw_yields_none_slots(self):
        # Reproduces build_notice's old `if detail and detail.content` guard:
        # an empty body must give None, not "".
        doc = await DEFAULT_PIPELINE.run(ContentDoc(raw=""), _ctx())
        assert doc.content is None
        assert doc.clean_html is None
        assert doc.text is None
        assert doc.markdown is None
        assert doc.content_hash is None


class TestSizeGuard:
    async def test_nulls_both_slots_when_oversized(self):
        oversized = "<p>" + ("x" * (MAX_CONTENT_BYTES + 10)) + "</p>"
        doc = ContentDoc(raw="<p>raw</p>", clean_html=oversized, content="<p>kept?</p>")
        doc = await SizeGuard().apply(doc, _ctx(article_no=1))
        assert doc.clean_html is None
        assert doc.content is None

    async def test_keeps_slots_when_within_budget(self):
        doc = ContentDoc(raw="<p>ok</p>", clean_html="<p>ok</p>", content="<p>ok</p>")
        doc = await SizeGuard().apply(doc, _ctx(article_no=1))
        assert doc.clean_html == "<p>ok</p>"
        assert doc.content == "<p>ok</p>"

    async def test_runs_after_dimension_injection(self):
        """The guard must measure the injected HTML, not the pre-injection
        one — otherwise a body that only crosses 5MB once dimensions are
        added would be stored oversized."""
        stages = [s.name for s in DEFAULT_PIPELINE.stages]
        assert stages.index("inject-image-dimensions") < stages.index("size-guard")


class TestVerifyImages:
    async def test_dimensions_land_in_meta_and_inject_into_clean_html(self):
        doc = ContentDoc(
            raw="<p></p>",
            content='<p><img src="https://cdn.test/a.png"></p>',
            clean_html='<p><img src="https://cdn.test/a.png"></p>',
        )
        result = ImageCheckResult(checked=1, dimensions={"https://cdn.test/a.png": (800, 600)})
        with patch(
            "skkuverse_crawler.modules.notices.stages.verify_notice_images",
            AsyncMock(return_value=result),
        ):
            doc = await VerifyImages().apply(doc, _ctx(article_no=1))
        assert doc.meta["image_dimensions"] == {"https://cdn.test/a.png": (800, 600)}

        doc = await InjectImageDimensions().apply(doc, _ctx(article_no=1))
        assert 'width="800"' in doc.clean_html
        assert 'height="600"' in doc.clean_html

    async def test_verification_failure_is_swallowed(self):
        doc = ContentDoc(raw="<p></p>", content="<p></p>")
        with patch(
            "skkuverse_crawler.modules.notices.stages.verify_notice_images",
            AsyncMock(side_effect=RuntimeError("network down")),
        ):
            doc = await VerifyImages().apply(doc, _ctx(article_no=1))
        assert doc.meta["image_dimensions"] == {}

    async def test_pipeline_without_verify_images_makes_no_http_call(self):
        """The disable knob of adr-006 결정 ④: dropping the stage must
        remove the network dependency, not just its effect.

        Asserted with a call recorder, not a raising side_effect —
        verify_and_measure_images catches bare Exception (AssertionError
        included), so a raiser would be swallowed and prove nothing."""
        slimmed = DEFAULT_PIPELINE.without("verify-images", "inject-image-dimensions")
        spy = AsyncMock(return_value=ImageCheckResult())
        with patch(
            "skkuverse_crawler.modules.notices.stages.verify_notice_images", spy
        ):
            doc = await slimmed.run(ContentDoc(raw="<p>hi</p>"), _ctx(article_no=1))
        spy.assert_not_awaited()
        assert doc.clean_html is not None
        assert "image_dimensions" not in doc.meta


class TestSlotDerivations:
    async def test_text_markdown_and_hash_follow_clean_html(self):
        doc = await DEFAULT_PIPELINE.run(ContentDoc(raw="<p>본문</p>"), _ctx(article_no=1))
        assert doc.text == "본문"
        assert doc.markdown is not None and "본문" in doc.markdown
        assert doc.content_hash is not None

    async def test_hash_is_none_when_clean_html_is_none(self):
        doc = ContentDoc(raw="<p>x</p>", clean_html=None)
        doc = await ContentHash().apply(doc, _ctx())
        doc = await ToMarkdown().apply(doc, _ctx())
        doc = await ExtractText().apply(doc, _ctx())
        assert doc.content_hash is None
        assert doc.markdown is None
        assert doc.text is None


class TestBuildNoticeTwoPathParity:
    """build_notice keeps an inline derivation path for direct callers.
    It must produce exactly what the pipeline path produces, or the
    goldens stop covering the callers that skip the pipeline."""

    @pytest.mark.parametrize(
        "raw_content",
        [
            "<p>평범한 본문</p>",
            '<p><img src="/img/a.png">사진</p>',
            '<table><tr><td>셀1</td><td>셀2</td></tr></table>',
            "",
            None,
        ],
    )
    async def test_paths_agree(self, raw_content):
        item = NoticeListItem(
            articleNo=1,
            title="제목",
            category="공지",
            author="관리자",
            date="2026-01-01",
            views=3,
            detailPath="?no=1",
        )
        detail = NoticeDetail(content=raw_content, contentText="폴백 텍스트", attachments=[])
        kwargs = dict(department="테스트학과", source_id="test-dept", base_url=BASE_URL)

        inline = build_notice(item, detail, **kwargs)

        doc = await DEFAULT_PIPELINE.without("verify-images").run(
            ContentDoc(raw=detail.content), _ctx(article_no=item.articleNo)
        )
        piped = build_notice(item, detail, **kwargs, content=doc)

        assert inline.content == piped.content
        assert inline.cleanHtml == piped.cleanHtml
        assert inline.contentText == piped.contentText
        assert inline.cleanMarkdown == piped.cleanMarkdown
        assert inline.contentHash == piped.contentHash

    async def test_paths_agree_when_the_detail_page_is_missing(self):
        """The real absent-content case is `detail=None` (orchestrator
        passes it when crawl_detail returns nothing) — distinct from a
        detail whose body is empty, and not covered by the parametrization
        above because that one always supplies a NoticeDetail."""
        item = NoticeListItem(
            articleNo=5,
            title="제목",
            category="",
            author="",
            date="2026-01-01",
            views=0,
            detailPath="?no=5",
        )
        kwargs = dict(department="테스트학과", source_id="test-dept", base_url=BASE_URL)

        inline = build_notice(item, None, **kwargs)
        doc = await DEFAULT_PIPELINE.without("verify-images").run(
            ContentDoc(raw=None), _ctx(article_no=item.articleNo)
        )
        piped = build_notice(item, None, **kwargs, content=doc)

        assert inline.content == piped.content is None
        assert inline.cleanHtml == piped.cleanHtml is None
        assert inline.contentText == piped.contentText is None
        assert inline.cleanMarkdown == piped.cleanMarkdown
        assert inline.contentHash == piped.contentHash is None

    async def test_paths_agree_with_image_dimensions(self):
        """The inline path's injection branch — reachable only via the
        image_dimensions argument, which the pipeline path replaces with
        InjectImageDimensions. Without this case the parity pin would not
        cover injection at all."""
        item = NoticeListItem(
            articleNo=3,
            title="포스터",
            category="공지",
            author="관리자",
            date="2026-01-01",
            views=0,
            detailPath="?no=3",
        )
        url = "https://cdn.test/poster.png"
        detail = NoticeDetail(
            content=f'<p><img src="{url}">포스터</p>', contentText="", attachments=[]
        )
        dimensions = {url: (891, 1260)}
        kwargs = dict(department="테스트학과", source_id="test-dept", base_url=BASE_URL)

        inline = build_notice(item, detail, **kwargs, image_dimensions=dimensions)

        with patch(
            "skkuverse_crawler.modules.notices.stages.verify_notice_images",
            AsyncMock(return_value=ImageCheckResult(checked=1, dimensions=dimensions)),
        ):
            doc = await DEFAULT_PIPELINE.run(
                ContentDoc(raw=detail.content), _ctx(article_no=item.articleNo)
            )
        piped = build_notice(item, detail, **kwargs, content=doc)

        assert 'width="891"' in inline.cleanHtml
        assert inline.cleanHtml == piped.cleanHtml
        assert inline.cleanMarkdown == piped.cleanMarkdown
        assert inline.contentHash == piped.contentHash

    async def test_passing_both_content_and_dimensions_is_refused(self):
        """They mean the same thing applied twice — a caller bug, so it
        must not silently pick one."""
        item = NoticeListItem(
            articleNo=4,
            title="t",
            category="",
            author="",
            date="2026-01-01",
            views=0,
            detailPath="?no=4",
        )
        detail = NoticeDetail(content="<p>x</p>", contentText="", attachments=[])
        with pytest.raises(ValueError, match="not both"):
            build_notice(
                item,
                detail,
                department="d",
                source_id="test-dept",
                base_url=BASE_URL,
                content=ContentDoc(raw="<p>x</p>"),
                image_dimensions={"https://cdn.test/a.png": (1, 1)},
            )

    async def test_contenttext_falls_back_to_detail_only_without_clean_html(self):
        item = NoticeListItem(
            articleNo=2,
            title="t",
            category="",
            author="",
            date="2026-01-01",
            views=0,
            detailPath="?no=2",
        )
        detail = NoticeDetail(content=None, contentText="상세 텍스트", attachments=[])
        doc = await DEFAULT_PIPELINE.without("verify-images").run(
            ContentDoc(raw=None), _ctx(article_no=2)
        )
        notice = build_notice(
            item,
            detail,
            department="d",
            source_id="test-dept",
            base_url=BASE_URL,
            content=doc,
        )
        assert notice.contentText == "상세 텍스트"
