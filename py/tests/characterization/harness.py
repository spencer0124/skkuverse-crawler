"""Golden-crawl harness: run run_crawl() against fixtures, snapshot 4 artifacts.

Per golden case: ``ops`` (FakeCollection round trips, order + args), ``state``
(final collection), ``result`` (DeptResult), ``log_events`` (structlog event
names in order — fixes the control-flow path without exposing internals).

Injection points (src/ stays untouched):
- ``orchestrator.get_db`` — patched at the *binding site* (the module-level
  ``from ..shared.db import get_db`` makes patching shared.db a no-op).
- ``Fetcher._rate_limit`` — no-op'd. ``run_crawl`` hardcodes
  ``delay_ms or 500`` so 0 is unreachable via options; patching the method
  (not asyncio.sleep) leaves retry backoff semantics observable.
- HTTP — one catch-all respx route feeding ``FixtureRouter``; any URL without
  a registered fixture is a loud AssertionError, which is also what enforces
  the "no <img> in fixtures" rule.

Snapshots are plain JSON files, regenerated with
``UPDATE_GOLDEN=1 pytest tests/characterization`` and reviewed by hand.
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import respx
from structlog.testing import capture_logs

from skkuverse_crawler.shared.fetcher import Fetcher
from tests.support.fake_mongo import FakeCollection, FakeDatabase
from tests.support.normalize import normalize_bson, sort_docs

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "html"
SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"


class FixtureRouter:
    """URL → canned fixture body; un-routed URLs fail loudly."""

    def __init__(self) -> None:
        self._responses: dict[str, str] = {}
        self._errors: dict[str, Exception] = {}
        self.requested: list[str] = []

    def serve(self, url: str, fixture_rel_path: str) -> "FixtureRouter":
        self._responses[url] = (FIXTURES_DIR / fixture_rel_path).read_text()
        return self

    def fail(self, url: str, exc: Exception) -> "FixtureRouter":
        self._errors[url] = exc
        return self

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requested.append(url)
        if url in self._errors:
            raise self._errors[url]
        if url in self._responses:
            return httpx.Response(200, text=self._responses[url])
        raise AssertionError(f"golden crawl requested an un-routed URL: {url}")


@dataclass
class GoldenRun:
    collection: FakeCollection
    results: list[Any]
    logs: list[dict[str, Any]]
    ops_start: int = 0

    def ops_delta(self) -> Any:
        """Round trips issued by THIS run (multi-round cases share a collection)."""
        return normalize_bson(
            self.collection.ops[self.ops_start :], datetime_to="placeholder", drop_id=False
        )

    def state(self) -> Any:
        return sort_docs(normalize_bson(self.collection.docs, datetime_to="placeholder"))

    def result(self) -> Any:
        normalized = []
        for dept_result in self.results:
            data = asdict(dept_result)
            data["duration_ms"] = 0
            normalized.append(data)
        return normalized

    def log_events(self) -> list[str]:
        return [entry["event"] for entry in self.logs]

    def snapshot_all(self, case: str, prefix: str = "") -> None:
        name = f"{prefix}_" if prefix else ""
        assert_snapshot(case, f"{name}ops", self.ops_delta())
        assert_snapshot(case, f"{name}state", self.state())
        assert_snapshot(case, f"{name}result", self.result())
        assert_snapshot(case, f"{name}log_events", self.log_events())


def seed(collection: FakeCollection, docs: list[dict[str, Any]]) -> None:
    """Pre-populate state without polluting the ops log (e.g. null-content docs)."""
    for doc in docs:
        collection.docs.append(copy.deepcopy(doc))


async def run_golden(
    dept: dict,
    router: FixtureRouter,
    *,
    collection: FakeCollection | None = None,
    incremental: bool = True,
    max_pages: int | None = None,
) -> GoldenRun:
    from skkuverse_crawler.notices.orchestrator import CrawlOptions, run_crawl

    collection = collection if collection is not None else FakeCollection()
    fake_db = FakeDatabase()
    fake_db.collections["notices"] = collection

    async def fake_get_db() -> FakeDatabase:
        return fake_db

    async def noop_rate_limit(self: Fetcher) -> None:
        return None

    ops_start = len(collection.ops)
    with (
        patch("skkuverse_crawler.notices.orchestrator.get_db", side_effect=fake_get_db),
        patch.object(Fetcher, "_rate_limit", noop_rate_limit),
        respx.mock(assert_all_called=False) as respx_router,
        capture_logs() as logs,
    ):
        respx_router.route().mock(side_effect=router.handler)
        results = await run_crawl(
            [dept], CrawlOptions(incremental=incremental, max_pages=max_pages)
        )
    return GoldenRun(collection=collection, results=results, logs=logs, ops_start=ops_start)


def assert_snapshot(case: str, artifact: str, data: Any) -> None:
    """Compare (or with UPDATE_GOLDEN=1, write) one snapshot file.

    Structural compare first for a readable pytest diff, then byte compare —
    the byte identity is the actual contract.
    """
    path = SNAPSHOTS_DIR / case / f"{artifact}.json"
    payload = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if os.environ.get("UPDATE_GOLDEN"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload)
        return
    assert path.exists(), (
        f"missing golden snapshot {path} — generate with "
        f"UPDATE_GOLDEN=1 pytest tests/characterization, then review and commit"
    )
    on_disk = path.read_text()
    assert json.loads(on_disk) == data, f"golden mismatch: {path}"
    assert on_disk == payload, f"golden byte mismatch (formatting drift): {path}"
