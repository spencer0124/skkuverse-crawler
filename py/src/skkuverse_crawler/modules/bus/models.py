"""What the bus modules hand to a sink.

`SnapshotSink` reads two attributes off an item by duck typing — `.key`
(the document `_id`) and `.fields` (merged into `$set` verbatim) — and
says so in a TypeError naming both if either is absent. This is that
shape, and deliberately nothing else: the sink is the second archetype's
whole storage story (adr-008 ①), so an item that grew a third attribute
would be describing a policy the sink cannot honour.

`key` arrives already shadow-suffixed. `sources.document_id` is the one
place that decision is made, and passing a `CacheKey` here instead would
mean every construction site had to remember to apply it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CacheSnapshot:
    """One `bus_cache`-shaped document.

    The payload nests under `data` because that is what skkuverse-server
    writes and therefore what its `read()` returns — the field name is a
    contract with the app, not a container this port chose.
    """

    key: str
    fields: Mapping[str, Any]
