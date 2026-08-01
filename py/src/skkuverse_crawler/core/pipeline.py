"""Content pipeline vocabulary (adr-006 결정 ④, architecture §Stage).

Fan-out, not a chain: every derived slot of a ContentDoc is computed from
``raw`` (or refines its own slot in place, like dimension injection) —
never from a sibling derivation. normalizer.py derives cleanHtml and
content independently from the raw detail HTML; wiring stages as a linear
chain would hand clean_html an already-normalized string and silently
rewrite every notice's cleanHtml (adr-006 §④).

Infra-free by contract — importing this module must never pull in
motor/pymongo (pinned by tests/structure test_core_import_is_infra_free).
Concrete stages live with the module that owns the content semantics
(modules/notices/stages.py); core defines only the shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ContentDoc:
    """One item's content in flight through the pipeline.

    ``raw`` is the untouched detail HTML; stages read it, not each other.
    ``meta`` is the extension surface for stages whose product is not a
    content slot (e.g. measured image dimensions).
    """

    raw: str | None
    content: str | None = None
    clean_html: str | None = None
    text: str | None = None
    markdown: str | None = None
    content_hash: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StageContext:
    """Per-item invariants a stage may need beyond the doc itself.

    ``logger`` is deliberately untyped: core stays free of the logging
    implementation; stages that log receive whatever the caller binds.
    """

    source_id: str = ""
    base_url: str = ""
    article_no: int | None = None
    logger: Any = None


class Stage(Protocol):
    name: str

    async def apply(self, doc: ContentDoc, ctx: StageContext) -> ContentDoc: ...


@dataclass(frozen=True)
class Pipeline:
    """An ordered application of stages over one ContentDoc.

    Order is meaningful even though derivations fan out from ``raw``:
    same-slot refinements must see their inputs in place (dimension
    injection before the size guard measures the injected HTML).
    """

    stages: tuple[Stage, ...] = ()

    async def run(self, doc: ContentDoc, ctx: StageContext) -> ContentDoc:
        for stage in self.stages:
            doc = await stage.apply(doc, ctx)
        return doc

    def without(self, *names: str) -> Pipeline:
        """A copy with the named stages removed — the disable knob of
        adr-006 결정 ④ (기본 on, 비활성화 가능)."""
        dropped = set(names)
        return Pipeline(tuple(s for s in self.stages if s.name not in dropped))
