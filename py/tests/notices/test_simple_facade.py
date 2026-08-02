"""iter_notices — the assembly, since the crawl logic is not its own.

The facade contains zero lines of crawl logic; it picks a source, builds a
strategy and a fetcher, and filters iter_source. So these tests assert the
arguments it assembles and the resources it releases, and leave "does the
crawl work" to the golden suite and the live CI examples.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from skkuverse_crawler.core.crawl import FullSweep
from skkuverse_crawler.core.events import (
    ItemSkipped,
    NoticeCrawled,
    PageCompleted,
    SourceFinished,
    SourceStarted,
)
from skkuverse_crawler.core.ports import NullWorkSeed
from skkuverse_crawler.modules.notices.cli import STORE_LESS_DEFAULT_PAGES
from skkuverse_crawler.modules.notices.constants import SERVICE_START_DATE
from skkuverse_crawler.modules.notices.simple import DEFAULT_MAX_PAGES, iter_notices
from skkuverse_crawler.modules.notices.simple import logger as module_logger

SOURCE = {
    "id": "fake-dept",
    "name": "가짜학과",
    "strategy": "skku-standard",
    "baseUrl": "https://example.com",
}


class _SpyFetcher:
    """Records that close() happened, which is the whole point."""

    instances: list[_SpyFetcher] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False
        _SpyFetcher.instances.append(self)

    async def close(self) -> None:
        self.closed = True


def _notice(article_no: int):
    from skkuverse_crawler.modules.notices.models import Notice

    return Notice(
        articleNo=article_no,
        title=f"공지 {article_no}",
        category="일반",
        author="관리자",
        department="가짜학과",
        date="2026-04-01",
        views=1,
        content=None,
        contentText=None,
        cleanHtml=None,
        attachments=[],
        sourceUrl=f"https://example.com/{article_no}",
        detailPath=f"?articleNo={article_no}",
        sourceId="fake-dept",
    )


def _event_stream(*, notices=(1, 2, 3)):
    """A stand-in iter_source: both tiers, in the order the real one emits."""
    calls: dict = {}

    async def fake_iter_source(dept, strategy, **kwargs):
        calls["dept"] = dept
        calls["strategy"] = strategy
        calls.update(kwargs)
        yield SourceStarted(source_id="fake-dept", source_name="가짜학과")
        yield ItemSkipped(source_id="fake-dept", article_no=99, reason="below_floor")
        for n in notices:
            yield NoticeCrawled(source_id="fake-dept", notice=_notice(n))
        yield PageCompleted(source_id="fake-dept", page=0)
        yield SourceFinished(
            source_id="fake-dept", stopped_by="max_pages", source_down=False, last_error=""
        )

    return fake_iter_source, calls


@pytest.fixture(autouse=True)
def _spy_fetcher():
    _SpyFetcher.instances = []
    with patch("skkuverse_crawler.modules.notices.simple.Fetcher", _SpyFetcher):
        yield


async def test_yields_notices_and_drops_every_other_event():
    fake, _ = _event_stream()
    with patch("skkuverse_crawler.modules.notices.simple.iter_source", fake):
        got = [n async for n in iter_notices(SOURCE)]

    assert [n.articleNo for n in got] == [1, 2, 3]


async def test_assembles_a_store_less_full_sweep():
    fake, calls = _event_stream()
    with patch("skkuverse_crawler.modules.notices.simple.iter_source", fake):
        [n async for n in iter_notices(SOURCE)]

    # FullSweep is not a choice here: with no seen index there is nothing
    # to be incremental against.
    assert isinstance(calls["mode"], FullSweep)
    assert isinstance(calls["work_seed"], NullWorkSeed)
    assert calls["options"].max_pages == DEFAULT_MAX_PAGES
    assert calls["options"].since_date == SERVICE_START_DATE


def test_the_cli_and_the_facade_share_one_page_default():
    """Both casual entry points guard against the FullSweep default of
    2500 pages across ~140 university servers. Two copies of that guard is
    how they end up disagreeing."""
    assert STORE_LESS_DEFAULT_PAGES == DEFAULT_MAX_PAGES == 1


async def test_the_fetcher_is_closed_when_iteration_finishes():
    fake, _ = _event_stream()
    with patch("skkuverse_crawler.modules.notices.simple.iter_source", fake):
        [n async for n in iter_notices(SOURCE)]

    assert _SpyFetcher.instances[0].closed


async def test_the_fetcher_is_closed_when_the_consumer_breaks_early():
    """The case a plain try/finally in a coroutine would not cover: an
    async generator abandoned mid-iteration only runs its finally on
    close(), which `async for` + `break` triggers via the loop's cleanup."""
    fake, _ = _event_stream()
    with patch("skkuverse_crawler.modules.notices.simple.iter_source", fake):
        stream = iter_notices(SOURCE)
        async for _notice_ in stream:
            break
        await stream.aclose()

    assert _SpyFetcher.instances[0].closed


async def test_delay_reaches_the_fetcher():
    fake, calls = _event_stream()
    with patch("skkuverse_crawler.modules.notices.simple.iter_source", fake):
        [n async for n in iter_notices(SOURCE, delay_ms=1200)]

    assert _SpyFetcher.instances[0].kwargs["delay_ms"] == 1200
    assert calls["options"].delay_ms == 1200


async def test_the_default_logger_is_the_real_one_not_a_silent_stub():
    """A silencing stub was tried and removed. It reaches only the crawl
    loop — the config loader and every strategy hold their own
    module-level structlog loggers — so it produced a partial silence:
    strategy fetch lines visible, the loop's own stopping reason hidden.
    Verbosity is structlog's job, and the caller's, not the facade's."""
    fake, calls = _event_stream()
    with patch("skkuverse_crawler.modules.notices.simple.iter_source", fake):
        [n async for n in iter_notices(SOURCE)]

    assert calls["logger"] is module_logger


async def test_a_caller_supplied_logger_is_used_as_is():
    fake, calls = _event_stream()
    sentinel = object()
    with patch("skkuverse_crawler.modules.notices.simple.iter_source", fake):
        [n async for n in iter_notices(SOURCE, log=sentinel)]

    assert calls["logger"] is sentinel


async def test_a_string_source_is_looked_up_in_sources_json():
    fake, calls = _event_stream()
    with (
        patch("skkuverse_crawler.modules.notices.simple.iter_source", fake),
        patch(
            "skkuverse_crawler.modules.notices.simple.load_and_validate",
            return_value=[{"id": "other"}, SOURCE],
        ),
    ):
        [n async for n in iter_notices("fake-dept")]

    assert calls["dept"]["id"] == "fake-dept"


async def test_an_unknown_source_id_is_a_value_error():
    """Not SourceConfigError: the config file is fine, the caller made a
    typo — the same line run_crawl draws for an unknown --source."""
    with patch(
        "skkuverse_crawler.modules.notices.simple.load_and_validate",
        return_value=[{"id": "other"}],
    ):
        with pytest.raises(ValueError, match="unknown source id"):
            [n async for n in iter_notices("nope")]


async def test_an_unknown_strategy_is_a_value_error():
    with pytest.raises(ValueError, match="unknown strategy"):
        [n async for n in iter_notices({**SOURCE, "strategy": "telepathy"})]


async def test_a_disabled_source_is_still_crawlable_by_name():
    """Unlike the scheduled crawl, the facade does not consult
    crawlAvailable/crawlEnabled. Naming a source is a stronger signal than
    a deployment default — and the alternative is a facade that returns an
    empty stream with no explanation."""
    fake, calls = _event_stream()
    paused = {**SOURCE, "crawlAvailable": True, "crawlEnabled": False}
    with (
        patch("skkuverse_crawler.modules.notices.simple.iter_source", fake),
        patch(
            "skkuverse_crawler.modules.notices.simple.load_and_validate",
            return_value=[paused],
        ),
    ):
        got = [n async for n in iter_notices("fake-dept")]

    assert [n.articleNo for n in got] == [1, 2, 3]
    assert calls["dept"]["crawlEnabled"] is False


async def test_a_mapping_source_never_reads_sources_json():
    """The escape hatch for a caller with their own config: passing a dict
    must not require the bundled sources.json to be resolvable at all."""
    fake, _ = _event_stream()

    def _explode():
        raise AssertionError("load_and_validate was called for a dict source")

    with (
        patch("skkuverse_crawler.modules.notices.simple.iter_source", fake),
        patch("skkuverse_crawler.modules.notices.simple.load_and_validate", _explode),
    ):
        got = [n async for n in iter_notices(SOURCE)]

    assert len(got) == 3
