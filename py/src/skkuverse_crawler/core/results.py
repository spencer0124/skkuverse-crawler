from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SourceResult:
    """Per-source crawl outcome. Moved from notices.orchestrator.DeptResult
    (adr-006): crawl_health consumes this, and importing it from the
    orchestrator dragged motor into the health import graph.

    The fields are ``source_*``, not ``dept_*``: a source is a department
    only for the notices module. crawl_health has always stored them as
    ``sourceId``/``sourceName`` (plugins/health/logic.py), so this makes the
    code agree with the storage it already writes.
    """

    source_id: str = ""
    source_name: str = ""
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    duration_ms: int = 0
    # Page-0 list fetch failed → the source is unreachable as a whole
    # (crawl-health alert signal). Partial mid-crawl errors don't set this.
    source_down: bool = False
    last_error: str = ""
