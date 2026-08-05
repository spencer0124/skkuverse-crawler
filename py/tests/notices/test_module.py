"""NoticesModule — the injection seam wiring assembles (plan PR 7).

What matters here is not the crawl (the goldens own that) but the three
things the module now owns: a fresh ports bundle per run, the bool→mode
translation, and the post-run hook that only exists on the scheduler path.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from skkuverse_crawler.core.crawl import FullSweep, Incremental
from skkuverse_crawler.core.ports import Ports
from skkuverse_crawler.core.results import SourceResult
from skkuverse_crawler.modules.notices.module import NoticesModule


class _CountingFactory:
    """Hands out a distinct bundle per call and remembers how many."""

    def __init__(self) -> None:
        self.calls = 0
        self.handed_out: list[Ports] = []

    async def __call__(self):
        self.calls += 1
        ports = Ports()
        self.handed_out.append(ports)
        return ports, _FakeSeen()


class _FakeSeen:
    async def lookup(self, source_id, article_nos):
        return {}


@contextmanager
def _patched(run_crawl_mock):
    with (
        patch(
            "skkuverse_crawler.modules.notices.module.load_and_validate",
            return_value=[{"id": "d", "name": "D"}],
        ),
        patch("skkuverse_crawler.modules.notices.module.run_crawl", run_crawl_mock),
    ):
        yield


async def test_ports_factory_is_awaited_once_per_run():
    """The Ports-lifetime contract (plan PR 7 ⚠️): MongoSink's prepare
    guard and touch buffer are instance state, so a bundle reused across
    runs would skip ensure_indexes on run 2 and could leak a failed
    flush's touches into run 3."""
    factory = _CountingFactory()
    run_crawl = AsyncMock(return_value=[])
    module = NoticesModule(ports_factory=factory)

    with _patched(run_crawl):
        await module.run()
        await module.run()

    assert factory.calls == 2
    # ...and run 2 must actually USE run 2's bundle. Calling the factory
    # twice while reusing the first bundle would satisfy the count alone.
    assert run_crawl.await_args.kwargs["ports"] is factory.handed_out[1]


async def test_incremental_true_builds_incremental_mode_over_the_factory_index():
    factory = _CountingFactory()
    run_crawl = AsyncMock(return_value=[])
    module = NoticesModule(ports_factory=factory)

    with _patched(run_crawl):
        await module.run(incremental=True)

    mode = run_crawl.await_args.kwargs["mode"]
    assert isinstance(mode, Incremental)
    assert run_crawl.await_args.kwargs["ports"] is factory.handed_out[0]


async def test_incremental_false_builds_full_sweep():
    factory = _CountingFactory()
    run_crawl = AsyncMock(return_value=[])
    module = NoticesModule(ports_factory=factory)

    with _patched(run_crawl):
        await module.run(incremental=False)

    assert isinstance(run_crawl.await_args.kwargs["mode"], FullSweep)


async def test_without_a_factory_there_is_nothing_to_be_incremental_over():
    """A module assembled with no store cannot consult one — asking for
    incremental must not fabricate an index."""
    run_crawl = AsyncMock(return_value=[])
    module = NoticesModule()

    with _patched(run_crawl):
        await module.run(incremental=True)

    assert isinstance(run_crawl.await_args.kwargs["mode"], FullSweep)
    assert run_crawl.await_args.kwargs["ports"] is None


async def test_results_hook_receives_the_crawl_results():
    results = [SourceResult(source_id="d", source_name="D", inserted=2)]
    run_crawl = AsyncMock(return_value=results)
    hook = AsyncMock()
    module = NoticesModule(ports_factory=_CountingFactory(), on_results=hook)

    with _patched(run_crawl):
        summary = await module.run()

    hook.assert_awaited_once_with(results)
    assert summary["inserted"] == 2


async def test_absent_hook_is_a_no_op():
    """The --once CLI path assembles no hook, which is what keeps manual
    runs free of health-state side effects (crawl_health/store contract)."""
    run_crawl = AsyncMock(return_value=[SourceResult(source_id="d", source_name="D")])
    module = NoticesModule(ports_factory=_CountingFactory())

    with _patched(run_crawl):
        summary = await module.run()

    assert summary["departments"] == 1
