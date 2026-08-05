"""JsonLinesSink — core's only concrete sink.

It is what makes `pip install skkuverse-crawler` produce visible output,
so the things worth pinning are: it satisfies the Sink protocol, it is
tolerant of events it does not recognise, and its output is parseable
JSON with no Python repr leaking through.
"""

from __future__ import annotations

import dataclasses
import io
import json
from datetime import datetime, timezone

from skkuverse_crawler.core.events import (
    BatchCompleted,
    ContentRefreshed,
    CrawlEvent,
    ItemCrawled,
    SourceFinished,
    SourceStarted,
)
from skkuverse_crawler.core.ports import DetailRef, Sink, SourceSpec
from skkuverse_crawler.core.sinks import JsonLinesSink
from skkuverse_crawler.modules.notices.models import Notice


def _notice(**overrides) -> Notice:
    base = dict(
        articleNo=1,
        title="제목",
        category="공지",
        author="관리자",
        department="테스트학과",
        date="2026-01-01",
        views=3,
        content="<p>본문</p>",
        contentText="본문",
        cleanHtml="<p>본문</p>",
        attachments=[],
        sourceUrl="https://example.ac.kr/board?no=1",
        detailPath="?no=1",
        sourceId="test-dept",
    )
    base.update(overrides)
    return Notice(**base)


def _sink() -> tuple[JsonLinesSink, io.StringIO]:
    stream = io.StringIO()
    return JsonLinesSink(stream), stream


def test_satisfies_the_sink_protocol():
    sink, _ = _sink()
    assert isinstance(sink, Sink)


async def test_writes_one_json_object_per_crawled_notice():
    sink, stream = _sink()
    await sink.prepare(SourceSpec(source_id="test-dept", name="테스트"))
    await sink.accept(ItemCrawled(source_id="test-dept", item=_notice()))
    await sink.accept(ItemCrawled(source_id="test-dept", item=_notice(articleNo=2)))
    await sink.flush()

    lines = stream.getvalue().splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["articleNo"] for line in lines] == [1, 2]


async def test_output_is_json_not_python_repr():
    """asdict leaves datetimes as objects; json.dumps must not fall back to
    str() on something a consumer then cannot parse."""
    sink, stream = _sink()
    stamp = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    await sink.accept(ItemCrawled(source_id="d", item=_notice(crawledAt=stamp)))

    payload = json.loads(stream.getvalue())
    assert payload["crawledAt"] == stamp.isoformat()
    assert payload["title"] == "제목", "non-ASCII must survive, not become \\uXXXX"


async def test_korean_is_written_readably():
    sink, stream = _sink()
    await sink.accept(ItemCrawled(source_id="d", item=_notice()))
    assert "제목" in stream.getvalue()


async def test_content_refreshed_carries_its_article_number():
    sink, stream = _sink()
    await sink.accept(
        ContentRefreshed(
            source_id="d",
            ref=DetailRef(article_no=7, detail_path="?no=7"),
            fields={"cleanHtml": "<p>new</p>"},
        )
    )
    payload = json.loads(stream.getvalue())
    assert payload["articleNo"] == 7
    assert payload["cleanHtml"] == "<p>new</p>"


async def test_progress_events_are_ignored_not_errors():
    """The tolerant-reader contract: a sink returns None for anything it
    does not recognise instead of failing the crawl."""
    sink, stream = _sink()
    for event in (
        SourceStarted(source_id="d", source_name="D"),
        BatchCompleted(source_id="d", index=0),
        SourceFinished(
            source_id="d", stopped_by="max_pages", source_down=False, last_error=""
        ),
    ):
        assert await sink.accept(event) is None
    assert stream.getvalue() == ""


async def test_tolerates_an_event_type_it_has_never_heard_of():
    @dataclasses.dataclass(frozen=True)
    class _FutureEvent(CrawlEvent):
        payload: str = "surprise"

    sink, stream = _sink()
    assert await sink.accept(_FutureEvent(source_id="d")) is None
    assert stream.getvalue() == ""
