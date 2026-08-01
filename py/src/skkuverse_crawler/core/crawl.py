"""CrawlMode — incremental/full-sweep as a sum type (adr-006 결정 ② v2).

Replaces the v1 `CrawlOptions.incremental: bool` + NullSeenIndex-emergent
full sweep: "incremental without a seen index" is unrepresentable, and the
honest API default is FullSweep (Incremental cannot be constructed without
a real index).

WorkSeed is deliberately NOT part of the mode (adr-006 §⑫): the
null-content backfill runs unconditionally — "FullSweep + WorkSeed" is
current production behavior, not an illegal state.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ports import SeenIndex


@dataclass(frozen=True)
class Incremental:
    """Incremental crawl. Cannot exist without a SeenIndex."""

    seen: SeenIndex


@dataclass(frozen=True)
class FullSweep:
    """Full crawl. Consults no state — lookup is never called."""


# Plain alias on purpose (not a PEP 695 `type` statement): the runtime
# UnionType supports isinstance() for max_pages derivation, and match-arm
# exhaustiveness stays checkable via typing.assert_never.
CrawlMode = Incremental | FullSweep
