# Writing a sink

A **sink** is where crawled notices go. The crawl emits events; a sink decides what storing
one means. MongoDB is a sink. So is a JSON Lines stream, a Postgres table, a search index, or
a dict you keep in memory.

This is the extension point most people will use, so it is the one with the most written down.
Everything here is checkable: `assert_sink_contract` enforces the parts a test can reach, and
the rest is called out below precisely because it cannot.

> Related: [core/plugin architecture](core-plugin-architecture.md) ·
> [adr-006](decisions/adr-006-core-plugin-split.md) · [README](../README.md)

## The protocol

```python
from skkuverse_crawler.core import CrawlEvent, Outcome, SourceSpec

class MySink:
    async def prepare(self, source: SourceSpec) -> None: ...
    async def accept(self, event: CrawlEvent) -> Outcome | None: ...
    async def flush(self) -> None: ...
```

No base class to inherit — `Sink` is a `Protocol`, so anything with these three methods is a
sink. `wiring.py` does check `isinstance` at assembly time, which is why they are
`runtime_checkable`: a missing `flush` becomes a clear boot error instead of an
`AttributeError` three hours into a crawl.

| Method | Called | For |
|--------|--------|-----|
| `prepare` | once per source, before its first event | Setup that depends on the source. Must be idempotent — the Mongo sink creates its indexes here and guards against repeats. |
| `accept` | once per event, in emission order | Your storage. The return value matters for exactly one event type; see below. |
| `flush` | on every `PageCompleted`; `run_crawl` adds one more when a source's stream ends | Where a batching sink writes. Called on pages where nothing was buffered too. |

Return values from `prepare` and `flush` are never read. The suite does not check them, on
purpose: enforcing a rule the runner does not have would have third parties writing code to
satisfy a fiction.

The end-of-source flush is not redundant with the per-page one, and the reason is worth
knowing if you buffer: not every source reaches a `PageCompleted`. The null-content backfill
emits write-bearing events *before* the page loop, and a source whose page 0 fetch fails
breaks out before the first page completes. Those writes used to sit in the buffer forever
while the runner counted them as done.

So `flush` must tolerate an empty buffer — it will be called on pages that buffered nothing,
and again at the end.

> **If you drive `run_events` yourself**, the end-of-source flush is not yours. It lives in
> `run_crawl`, not in the runner — `core.runner.run_events` still flushes on `PageCompleted`
> and nothing else. Call `flush()` after the stream ends, and note that neither call is in a
> `finally`: an `accept` that raises still leaves your buffer un-drained.

### One sink, several sources at once

`run_crawl` builds one sink and hands the same instance to every source, which crawl
concurrently under a `Semaphore(5)`. So `accept` and `flush` interleave across sources: your
`flush` may drain work another source buffered mid-page.

Make every write carry its own identity — the Mongo sink puts `articleNo` + `sourceId` in each
op's filter and uses an unordered bulk write, so ops always land correctly no matter who
drains them. What that costs is failure *attribution*: a failing flush can lose a sibling
source's drained work while that source still reports success. That is a known pre-1.0 defect
(adr-006 §⑪), not a design you should copy.

## What `accept` returns

Only `NoticeCrawled` reads it, and it decides one number:

```python
case NoticeCrawled():
    if outcome is Outcome.UPDATED:
        result.updated += 1
    else:
        result.inserted += 1
```

So `Outcome.UPDATED` means *this item was already there*, `Outcome.INSERTED` means it was
new, and `None` is read as `INSERTED`. If your store cannot tell the difference cheaply,
returning `None` is honest and costs one wrong counter, not correctness.

Do not return the strings `"inserted"`/`"updated"`. The old code did, and the runner's
`is Outcome.UPDATED` check would silently count every one of them as inserted.

`ContentRefreshed` is the other event that carries a write, and the suite accepts an `Outcome`
or `None` from it — but the runner counts it as `updated` either way, so the value is
informational. For everything else the return is ignored and the suite requires `None`:
nothing was stored, so there is nothing to report.

## Tolerant reader

**Return `None` for any event you do not recognise. Never raise.**

```python
async def accept(self, event: CrawlEvent) -> Outcome | None:
    match event:
        case NoticeCrawled(notice=notice):
            ...
        case _:
            return None   # <- the whole progress tier, and anything added later
```

This is not politeness, it is the versioning mechanism. The event vocabulary has two tiers:

| Tier | Events | Promise |
|------|--------|---------|
| **Result** | `NoticeCrawled` `NoticeUnchanged` `ContentRefreshed` `ItemFailed` `ItemSkipped` | Frozen. Adding or changing one is a major release. |
| **Progress** | `SourceStarted` `PageCompleted` `ListFetchFailed` `SourceFinished` | May grow in a minor release. |

A progress event can be added in a minor release *only* because every sink ignores what it has
not heard of. A sink with an exhaustive match that raises on the unknown turns that minor
release into a breaking one for its own users.

The reverse has teeth too. If a future release misclassifies a write-bearing event as
progress, tolerant sinks will drop it silently rather than error — which is why the tier of a
new event is a review question, not a naming preference (adr-006 §⑧).

### The result-tier events

- **`NoticeCrawled`** — a fetched notice ready to store. `change=None` is a new or replaced
  item (plain upsert). A populated `change` is an edit detected against what you already had:
  same article, different title or content hash. The Mongo sink treats that as a
  history-preserving update; a simpler sink can treat both the same.
- **`NoticeUnchanged`** — a known item that did not change. Usually batched and written on
  `flush` as a "seen at" refresh. Ignoring it entirely is valid; it costs you the ability to
  tell a stale record from a deleted one.
- **`ContentRefreshed`** — backfilled content for an item stored earlier without any.
  Deliberately not the upsert path: it carries an explicit field list and no history, because
  routing it through the normal path would rewrite `cleanHtml` for every backfilled document.
- **`ItemFailed`** / **`ItemSkipped`** — an item that was *not* stored. The runner counts
  them; sinks normally ignore them.

## Three rules a test cannot check

### Do not buffer the events themselves

`NoticeCrawled` holds a `Notice`, and a `Notice` can carry several megabytes of `cleanHtml`.
Publishing the event is free — it is a reference — but a sink that appends events to a list
keeps every one of those payloads alive until the crawl ends.

```python
# no — keeps the whole Notice, cleanHtml and all, until the crawl ends
self._pending.append(event)

# yes — only the fields you will actually write
self._pending.append({"articleNo": event.notice.articleNo, "title": event.notice.title})
```

`MongoSink._touches` is the reference implementation. Only a memory profile would catch the
first version, which is why it is written here instead.

### Let `flush` fail

A failing flush must propagate. It aborts that source's crawl and `run_crawl` logs
`department_crawl_failed`; the source is then **absent from the returned results** rather than
present with an error count. That is the contract (adr-006 §⑪), not an accident of the current
code — but note what it means for you: a caller reading the results cannot tell a dropped
source from one that was never asked for.

```python
# no — the crawl now reports success for a source whose writes vanished
async def flush(self) -> None:
    try:
        await self._write_batch()
    except Exception:
        logger.warning("flush failed")
```

Whether to retry inside `flush` is yours to decide. Whether to *hide* the failure is not.

### Build a sink per run, not per process

`prepare`-once guards and buffers are instance state. Reuse a sink across runs and the second
run skips setup; if a final flush failed, its leftover work leaks into the next run's batch.
`wiring.py` builds a fresh bundle for every run for exactly this reason.

## Check it

```python
from skkuverse_crawler.core.testing import assert_sink_contract

async def test_my_sink_satisfies_the_contract():
    await assert_sink_contract(MySink())
```

That call **stores nothing**, so it is safe against a sink pointed at a real store. It does
call `prepare`, because prepare is by definition your own idempotent setup.

To cover the write-bearing half, pass a sample. It has to come from you: the sample is a
`NoticeCrawled`, which holds a `Notice`, which belongs to the notices module — `core` cannot
build one without importing across its own layer boundary.

```python
sample = NoticeCrawled(source_id="my-source", notice=a_notice)
await assert_sink_contract(MySink(throwaway_store), sample=sample)
```

With a sample, expect writes. Point it at a scratch database, a fake collection or an
in-memory stream.

What the suite checks: the protocol shape, that unknown and progress-tier events return
`None`, that an empty `flush` is not an error, and that `accept` returns an `Outcome` or
`None` for the write-bearing events. What it cannot: the three rules above.

## A worked example

[`py/examples/custom_sink.py`](../py/examples/custom_sink.py) is a complete sink plus the crawl
that drives it, and CI runs it on every pull request. It is also embedded in the
[README](../README.md), byte for byte.

## Wiring it in

For your own program, hand it to `run_crawl`:

```python
from skkuverse_crawler.core import FullSweep, Ports
from skkuverse_crawler.modules.notices.orchestrator import CrawlOptions, run_crawl

await run_crawl(
    sources,
    CrawlOptions(max_pages=1, dept_filter=("skku-main",)),
    ports=Ports(sink=MySink()),
    mode=FullSweep(),
)
```

Name the sources you want with `dept_filter`. Without it `run_crawl` falls back to the
deployment default — the entries flagged `crawlAvailable` *and* `crawlEnabled` — which for a
hand-built list of sources usually means none of them, and an empty result with no error.

`Ports()` defaults to `NullSink`, which discards everything — the plugin-less configuration,
and a useful baseline when you want the crawl's counters without its output.

`FullSweep` versus `Incremental(seen)` is a separate axis: incremental needs a `SeenIndex`,
which is a second port and a second adapter. Without one, a full sweep is the only honest
mode — there is nothing to compare against — and the type system says so, because
`Incremental` cannot be constructed without an index.

## Stability

Pre-1.0. The tiers above describe the intent, and until 1.0 both are provisional — the 0.x
window is deliberately the last chance to correct the vocabulary before anyone depends on it.
1.0 waits on a second module actually running on this framework (adr-006 §⑬).

If you are maintaining a sink, the useful habit is to run `assert_sink_contract` in your own
test suite against your own implementation. It travels with the package, so it always
describes the version you have installed rather than the version this page was written for.
