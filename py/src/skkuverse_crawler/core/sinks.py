"""Core's only concrete sink: one JSON object per crawled item.

It exists because `pip install skkuverse-crawler` has to put results
somewhere. Every other sink is a plugin, and NullSink discards — without
this, a core-only install could crawl and then have nothing to show for
it, which would make "the core runs with no infrastructure" a claim
rather than a demonstration.

Stdlib only, by contract: this module is on the infra-free core import
path (pinned by tests/structure test_core_import_is_infra_free).
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import date, datetime
from typing import IO, Any

from .events import ContentRefreshed, CrawlEvent, ItemCrawled
from .ports import Outcome, SourceSpec


def _fallback(value: Any) -> str:
    """Serialise what JSON cannot, and refuse the rest.

    A blanket ``str(value)`` would turn an ObjectId into a 24-hex string a
    consumer cannot tell from a real string field, and bytes into
    ``"b'\\x00…'"``. Silent corruption is worse than a crash here: raising
    means a field that changes shape fails the crawl instead of emitting a
    plausible-looking lie.
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} is not JSON-serialisable")


class JsonLinesSink:
    """Writes write-bearing events as JSON Lines; ignores the rest.

    The tolerant-reader contract (architecture §이벤트 계층) applies here
    as much as to a third-party sink: progress events are not errors, they
    are simply not this sink's business, so they return None silently.
    """

    def __init__(self, stream: IO[str] | None = None) -> None:
        self._stream = stream if stream is not None else sys.stdout

    async def prepare(self, source: SourceSpec) -> None:
        return None

    async def accept(self, event: CrawlEvent) -> Outcome | None:
        if isinstance(event, ItemCrawled):
            # asdict, not a protocol call: core does not know the item's
            # schema and does not want to. A non-dataclass item is a
            # TypeError here rather than a half-serialised line.
            self._write(dataclasses.asdict(event.item))
        elif isinstance(event, ContentRefreshed):
            # sourceId keeps the two line shapes uniform — every other line
            # carries it, and a consumer merging sources needs it.
            self._write(
                {
                    "articleNo": event.ref.article_no,
                    "sourceId": event.source_id,
                    **event.fields,
                }
            )
        # Everything else — the whole progress tier and any event type this
        # sink has never heard of — is deliberately not an error.
        return None

    async def flush(self) -> None:
        self._stream.flush()

    def _write(self, payload: dict[str, Any]) -> None:
        # allow_nan=False: the default emits bare NaN/Infinity, which is
        # valid Python and invalid JSON — jq, JS and Go all reject it.
        self._stream.write(
            json.dumps(payload, ensure_ascii=False, allow_nan=False, default=_fallback) + "\n"
        )
