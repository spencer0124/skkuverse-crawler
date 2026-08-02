"""Pipeline vocabulary tests — order, slot independence, the disable knob.

The fan-out invariant itself (clean_html derives from raw, not content)
is a property of the concrete stages, pinned where they live
(tests/notices/test_stages.py); here we pin the machinery only.
"""

from __future__ import annotations

from dataclasses import dataclass

from skkuverse_crawler.core.pipeline import ContentDoc, Pipeline, Stage, StageContext


@dataclass(frozen=True)
class _Recorder:
    name: str
    log: list

    async def apply(self, doc: ContentDoc, ctx: StageContext) -> ContentDoc:
        self.log.append(self.name)
        return doc


class _DeriveContentFromRaw:
    name = "derive-content"

    async def apply(self, doc: ContentDoc, ctx: StageContext) -> ContentDoc:
        doc.content = f"normalized:{doc.raw}"
        return doc


class _DeriveCleanFromRaw:
    name = "derive-clean"

    async def apply(self, doc: ContentDoc, ctx: StageContext) -> ContentDoc:
        doc.clean_html = f"cleaned:{doc.raw}"
        return doc


async def test_stages_apply_in_order():
    log: list[str] = []
    pipeline = Pipeline((_Recorder("a", log), _Recorder("b", log), _Recorder("c", log)))
    await pipeline.run(ContentDoc(raw="x"), StageContext())
    assert log == ["a", "b", "c"]


async def test_slots_fan_out_from_raw_not_each_other():
    # Two derivation stages both read raw; the later one must not see the
    # earlier one's output as its input (adr-006 §④).
    pipeline = Pipeline((_DeriveContentFromRaw(), _DeriveCleanFromRaw()))
    doc = await pipeline.run(ContentDoc(raw="<p>hi</p>"), StageContext())
    assert doc.content == "normalized:<p>hi</p>"
    assert doc.clean_html == "cleaned:<p>hi</p>"


async def test_empty_pipeline_returns_doc_unchanged():
    doc = ContentDoc(raw="untouched")
    assert await Pipeline().run(doc, StageContext()) is doc


async def test_without_drops_named_stages():
    log: list[str] = []
    pipeline = Pipeline((_Recorder("keep", log), _Recorder("drop", log)))
    slimmed = pipeline.without("drop")
    assert [s.name for s in slimmed.stages] == ["keep"]
    # The original is untouched (Pipeline is a frozen value).
    assert [s.name for s in pipeline.stages] == ["keep", "drop"]


def test_stage_protocol_matches_conforming_class():
    stage: Stage = _DeriveContentFromRaw()
    assert stage.name == "derive-content"
