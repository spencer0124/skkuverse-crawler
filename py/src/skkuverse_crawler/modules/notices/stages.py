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

from dataclasses import dataclass
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
# Recorded by SizeGuard so a consumer can tell "the body was too big to
# store" from "the body sanitised to nothing" — both leave every content
# slot None, and they call for opposite handling.
OVERSIZED = "oversized"


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
        # Merged, not assigned: a caller may seed doc.meta with dimensions it
        # already knows (see derive_content_fields' known_dimensions). A live
        # measurement wins where there is one, but a host that was slow this
        # minute must not erase what was measured last time — the hash comes
        # from this HTML, so losing a dimension invents a content change.
        known = doc.meta.get(_IMAGE_DIMENSIONS) or {}
        doc.meta[_IMAGE_DIMENSIONS] = {**known, **result.dimensions}
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
            doc.meta[OVERSIZED] = True
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


@dataclass(frozen=True)
class ContentFields:
    """The five stored content fields, named as they are stored.

    camelCase on purpose: every consumer turns this into a Mongo ``$set``,
    and a snake_case type here would mean a hand-written mapping per caller
    — which is the drift this exists to end.
    """

    content: str | None
    contentText: str | None
    cleanHtml: str | None
    cleanMarkdown: str | None
    contentHash: str | None
    # Not stored. It answers "why is everything None", which a caller cannot
    # work out from the fields alone: an oversized body and a body that
    # sanitised to nothing look identical here, and only one of them should
    # be written through. Re-measuring the raw input is NOT a substitute —
    # clean_html can more than double the byte count by absolutising URLs,
    # so the raw size and the stored size fall on opposite sides of the
    # limit in both directions.
    oversized: bool = False

    @classmethod
    def from_doc(cls, doc: ContentDoc, *, fallback_text: str | None = None) -> ContentFields:
        # `text if clean_html else None` mirrors build_notice: a doc whose
        # HTML was dropped must not keep text extracted before the drop.
        text = doc.text if doc.clean_html else None
        return cls(
            content=doc.content,
            contentText=text if text is not None else (fallback_text or None),
            cleanHtml=doc.clean_html,
            cleanMarkdown=doc.markdown,
            contentHash=doc.content_hash,
            oversized=bool(doc.meta.get(OVERSIZED)),
        )

    def as_set(
        self, *, attachments: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """The stored fields a re-derivation owns.

        ``attachments`` is a parameter rather than a field because it is not
        derived from the content — it comes off the strategy. It belongs here
        anyway so that every writer names the same set: when Tier-2 wrote the
        content fields and left attachments alone, a board that rotates its
        attachment IDs (dorm) kept serving stale links, and one of them had
        already come to point at a different file entirely.
        """
        fields: dict[str, Any] = {
            "content": self.content,
            "contentText": self.contentText,
            "cleanHtml": self.cleanHtml,
            "cleanMarkdown": self.cleanMarkdown,
            "contentHash": self.contentHash,
        }
        if attachments is not None:
            fields["attachments"] = attachments
        return fields


async def derive_content_fields(
    raw_html: str | None,
    *,
    base_url: str,
    source_url: str = "",
    source_id: str = "",
    article_no: int | None = None,
    fallback_text: str | None = None,
    known_dimensions: dict[str, tuple[int, int]] | None = None,
    pipeline: Pipeline = DEFAULT_PIPELINE,
    log: Any = None,
) -> ContentFields:
    """Derive the stored content fields the way a crawl does — same pipeline.

    This exists because the Tier-2 update checker used to rebuild them by
    hand, and a hand-built copy cannot stay equal to a pipeline. It had
    drifted four ways, all silent:

    - no ``cleanMarkdown`` at all, so an edited notice kept rendering its
      old body in the app;
    - ``contentText`` taken from the strategy instead of extracted from the
      sanitized HTML, losing the block newlines added in 2026-04;
    - no size guard, so an oversized body was written where a crawl stores
      nulls;
    - and the one that made the others permanent: **no image measurement**.
      ``InjectImageDimensions`` puts width/height on every ``<img>``, the
      hash is taken from that HTML, and the markdown carries the ``{WxH}``
      hint the app parses. Deriving without it produced a *different hash
      for identical content*, so Tier-2 and the crawl overwrote each other
      forever — one notice reached editCount 30 across exactly two hashes.

    Running the real pipeline is what makes those unrepeatable. The cost is
    the image probe (``verify-images``), which is a no-op for a body with
    no images; drop it with ``pipeline=DEFAULT_PIPELINE.without("verify-images")``
    if a caller genuinely cannot spend it — and accept a hash that will not
    match a crawl's.
    """
    doc = await pipeline.run(
        # Seeding meta rather than passing an argument: dimensions are a
        # stage's product, and meta is the surface stages already use for
        # products that are not content slots.
        ContentDoc(
            raw=raw_html or None,
            meta={_IMAGE_DIMENSIONS: dict(known_dimensions)} if known_dimensions else {},
        ),
        StageContext(
            source_id=source_id,
            base_url=base_url,
            source_url=source_url,
            article_no=article_no,
            logger=log or logger,
        ),
    )
    return ContentFields.from_doc(doc, fallback_text=fallback_text)


# The tail of DEFAULT_PIPELINE — every stage that works from an already
# sanitized body. The three it drops are exactly the ones that need the raw
# detail HTML, which a stored document does not keep.
#
# Named by omission rather than by listing five stages, so that reordering
# or inserting a stage upstream cannot silently leave this behind.
REPAIR_PIPELINE = DEFAULT_PIPELINE.without("normalize-urls", "clean-html", "verify-images")


async def rederive_from_clean_html(
    clean_html: str | None,
    *,
    content: str | None = None,
    dimensions: dict[str, tuple[int, int]] | None = None,
    fallback_text: str | None = None,
    source_id: str = "",
    article_no: int | None = None,
    log: Any = None,
) -> ContentFields:
    """Rebuild the derived fields of a stored notice, without re-crawling.

    For repairing documents whose ``cleanHtml`` is current but whose
    downstream fields are not — the state Tier-2 left behind when it wrote
    sanitized HTML with no image dimensions and text taken from the
    strategy.

    It starts from ``cleanHtml`` on purpose and must: re-deriving it from
    the stored ``content`` would feed already-normalized HTML back through
    ``clean_html`` and silently rewrite every notice's body (adr-006 §④).
    The stored sanitized HTML *is* the body; only what hangs off it is
    stale.

    Idempotent — a document already consistent comes back with identical
    fields, which is what lets a caller write only on a real difference.
    """
    doc = await REPAIR_PIPELINE.run(
        ContentDoc(
            raw=None,
            content=content,
            clean_html=clean_html,
            meta={_IMAGE_DIMENSIONS: dict(dimensions)} if dimensions else {},
        ),
        StageContext(source_id=source_id, article_no=article_no, logger=log or logger),
    )
    return ContentFields.from_doc(doc, fallback_text=fallback_text)
