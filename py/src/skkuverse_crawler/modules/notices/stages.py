"""The notices content pipeline — concrete stages (architecture §Stage).

The dependency graph, exactly as it is (not a chain):

    raw ─┬─→ content        (NormalizeUrls)
         └─→ clean_html     (CleanHtml)  ← from raw, NOT from content

``content`` and ``clean_html`` are siblings. Deriving one from the other
would silently rewrite every notice's cleanHtml (adr-006 §④) — that is
the invariant worth protecting, and the only one this docstring asserts.

Everything downstream reads ``clean_html`` by design, because sanitized
HTML is what they are supposed to describe:

    clean_html ─→ text (ExtractText), markdown (ToMarkdown),
                  content_hash (ContentHash)

Pointing any of those at ``raw`` instead would put script/style and WPDM
download-block text into contentText — so do not "fix" them to read raw.

Three stages refine rather than derive. ``VerifyImages`` reads
``content`` (image ``src`` must be absolute to be fetchable) and writes
only ``doc.meta``; ``InjectImageDimensions`` and ``SizeGuard`` rewrite
``clean_html`` in place.

Order: dimension injection must precede the size guard, because the guard
measures the injected HTML. The goldens do NOT pin this — no fixture
contains an ``<img>``, so image stages are inert there. It is pinned by
tests/notices/test_stages.py.

Stage bodies are the pre-existing expressions verbatim; the guards
(``if doc.raw``) reproduce the old ``if detail and detail.content``
so an empty-string body still yields None rather than "".
"""

from __future__ import annotations

from typing import Any

from ...core.pipeline import ContentDoc, Pipeline, StageContext
from ...shared.html_cleaner import clean_html, normalize_content_urls
from ...shared.html_to_markdown import html_to_markdown
from ...shared.logger import get_logger
from .hashing import compute_content_hash
from .image_verifier import ImageCheckResult, verify_notice_images
from .normalizer import (
    MAX_CONTENT_BYTES,
    _inject_image_dimensions,
    _text_from_clean_html,
)

logger = get_logger("notices.stages")

_IMAGE_DIMENSIONS = "image_dimensions"


async def verify_and_measure_images(
    content_html: str | None,
    source_url: str,
    dept_id: str,
    article_no: int | None,
    logger_: Any,
) -> ImageCheckResult:
    """Best-effort image verification + dimension detection. Never raises."""
    try:
        result = await verify_notice_images(content_html, source_url)
        if result.broken:
            logger_.warning(
                "broken_notice_images",
                articleNo=article_no,
                dept_id=dept_id,
                checked=result.checked,
                broken_count=len(result.broken),
                broken=result.broken[:5],  # cap log payload
            )
        if result.dimensions:
            logger_.debug(
                "image_dimensions_detected",
                articleNo=article_no,
                count=len(result.dimensions),
            )
        return result
    except Exception as exc:
        logger_.warning(
            "image_verify_failed",
            articleNo=article_no,
            dept_id=dept_id,
            error=str(exc),
        )
        return ImageCheckResult()


class NormalizeUrls:
    """`content` — relative src/href resolved, structure otherwise intact."""

    name = "normalize-urls"

    async def apply(self, doc: ContentDoc, ctx: StageContext) -> ContentDoc:
        doc.content = normalize_content_urls(doc.raw, ctx.base_url) if doc.raw else None
        return doc


class CleanHtml:
    """`cleanHtml` — from raw, NOT from the normalized content."""

    name = "clean-html"

    async def apply(self, doc: ContentDoc, ctx: StageContext) -> ContentDoc:
        doc.clean_html = clean_html(doc.raw, ctx.base_url) if doc.raw else None
        return doc


class VerifyImages:
    """Optional (adr-006 결정 ④): the only stage that hits the network."""

    name = "verify-images"

    async def apply(self, doc: ContentDoc, ctx: StageContext) -> ContentDoc:
        result = await verify_and_measure_images(
            doc.content, ctx.source_url, ctx.source_id, ctx.article_no, ctx.logger or logger
        )
        doc.meta[_IMAGE_DIMENSIONS] = result.dimensions
        return doc


class InjectImageDimensions:
    name = "inject-image-dimensions"

    async def apply(self, doc: ContentDoc, ctx: StageContext) -> ContentDoc:
        dimensions = doc.meta.get(_IMAGE_DIMENSIONS)
        if doc.clean_html and dimensions:
            doc.clean_html = _inject_image_dimensions(doc.clean_html, dimensions)
        return doc


class SizeGuard:
    """Drops oversized bodies — both slots, after injection (§Stage)."""

    name = "size-guard"

    async def apply(self, doc: ContentDoc, ctx: StageContext) -> ContentDoc:
        if doc.clean_html and len(doc.clean_html.encode()) > MAX_CONTENT_BYTES:
            (ctx.logger or logger).warning(
                "oversized_content_dropped",
                articleNo=ctx.article_no,
                dept=ctx.source_id,
                size=len(doc.clean_html.encode()),
            )
            doc.clean_html = None
            doc.content = None
        return doc


class ExtractText:
    name = "extract-text"

    async def apply(self, doc: ContentDoc, ctx: StageContext) -> ContentDoc:
        doc.text = _text_from_clean_html(doc.clean_html) if doc.clean_html else None
        return doc


class ToMarkdown:
    name = "to-markdown"

    async def apply(self, doc: ContentDoc, ctx: StageContext) -> ContentDoc:
        doc.markdown = html_to_markdown(doc.clean_html)
        return doc


class ContentHash:
    name = "content-hash"

    async def apply(self, doc: ContentDoc, ctx: StageContext) -> ContentDoc:
        doc.content_hash = compute_content_hash(doc.clean_html)
        return doc


DEFAULT_PIPELINE = Pipeline(
    (
        NormalizeUrls(),
        CleanHtml(),
        VerifyImages(),
        InjectImageDimensions(),
        SizeGuard(),
        ExtractText(),
        ToMarkdown(),
        ContentHash(),
    )
)
