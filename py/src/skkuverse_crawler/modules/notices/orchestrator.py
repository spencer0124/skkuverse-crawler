from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator, Mapping
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any, assert_never

from ...core.crawl import CrawlMode, FullSweep, Incremental
from ...core.events import (
    ChangeInfo,
    ContentRefreshed,
    CrawlEvent,
    ItemFailed,
    ItemSkipped,
    ListFetchFailed,
    NoticeCrawled,
    NoticeUnchanged,
    PageCompleted,
    SourceFinished,
    SourceStarted,
)
from ...core.pipeline import ContentDoc, Pipeline, StageContext
from ...core.ports import Ports, SeenRecord, SourceSpec, WorkSeed
from ...core.runner import run_events
from ...core.results import SourceResult
from ...shared.fetcher import Fetcher
from ...shared.html_cleaner import clean_html, normalize_content_urls
from ...shared.html_to_markdown import html_to_markdown
from ...shared.logger import get_logger
from .constants import SERVICE_START_DATE
from .policy import has_changed, page_below_floor, should_continue
from .hashing import compute_content_hash
from .models import NoticeListItem
from .normalizer import MAX_CONTENT_BYTES, build_notice
from .stages import DEFAULT_PIPELINE
from .strategies import STRATEGY_MAP


@dataclass
class CrawlOptions:
    max_pages: int | None = None
    delay_ms: int | None = None
    dept_filter: tuple[str, ...] | None = None
    # Deployment policy, not a core constant (architecture ownership table):
    # the notices module supplies the current floor as the default.
    since_date: str | None = SERVICE_START_DATE


async def run_crawl(
    departments: list[dict[str, Any]],
    options: CrawlOptions,
    ports: Ports | None = None,
    mode: CrawlMode | None = None,
    pipeline: Pipeline = DEFAULT_PIPELINE,
) -> list[SourceResult]:
    crawl_id = uuid.uuid4().hex[:8]
    logger = get_logger("orchestrator", crawl_id=crawl_id)

    # Null objects, not lazy wiring: callers that want a store inject it
    # (wiring builds the bundle, NoticesModule and the CLI pass it in).
    # Defaults are the honest plugin-less configuration — no store to
    # consult means nothing is known, which is FullSweep
    # (architecture §CrawlMode).
    if ports is None:
        ports = Ports()
    if mode is None:
        mode = FullSweep()

    fetcher = Fetcher(delay_ms=options.delay_ms or 500)

    if options.dept_filter:
        valid_ids = {d["id"] for d in departments}
        unknown = [did for did in options.dept_filter if did not in valid_ids]
        if unknown:
            raise ValueError(
                f"Unknown department ID(s) in CRAWL_SOURCE_FILTER: {unknown}. "
                f"Check sources.json for valid IDs."
            )
        filtered = [d for d in departments if d["id"] in options.dept_filter]
    else:
        # No explicit filter: cron crawls only when BOTH structurally available
        # (crawlAvailable=true; not intentionally unsupported) AND operationally
        # enabled (crawlEnabled=true; not paused for testing/maintenance).
        filtered = [
            d for d in departments
            if d.get("crawlAvailable", False) and d.get("crawlEnabled", False)
        ]

    # attempted vs enabled, side by side, once per run. The 2026-04-21
    # incident (known-issues §7) went unnoticed for days because a stray
    # CRAWL_SOURCE_FILTER silently cut 132 sources and nobody was
    # comparing the two numbers — every individual log looked healthy.
    enabled = sum(
        1 for d in departments
        if d.get("crawlAvailable", False) and d.get("crawlEnabled", False)
    )
    logger.info(
        "crawl_coverage",
        attempted=len(filtered),
        enabled=enabled,
        total=len(departments),
        dept_filter=options.dept_filter,
    )

    if not filtered:
        logger.warning("no_matching_departments", dept_filter=options.dept_filter)
        return []

    for dept in filtered:
        await ports.sink.prepare(SourceSpec(source_id=dept["id"], name=dept["name"]))

    sem = asyncio.Semaphore(5)
    results: list[SourceResult] = []

    async def crawl_with_sem(dept: dict) -> SourceResult:
        async with sem:
            return await _crawl_department(
                dept, ports, fetcher, mode, options, logger, pipeline
            )

    tasks = [crawl_with_sem(dept) for dept in filtered]
    settled = await asyncio.gather(*tasks, return_exceptions=True)

    for r in settled:
        if isinstance(r, SourceResult):
            results.append(r)
        else:
            logger.error("department_crawl_failed", error=str(r))

    total_inserted = sum(r.inserted for r in results)
    total_updated = sum(r.updated for r in results)
    total_skipped = sum(r.skipped for r in results)
    total_errors = sum(r.errors for r in results)
    logger.info(
        "crawl_completed",
        departments=len(results),
        total_inserted=total_inserted,
        total_updated=total_updated,
        total_skipped=total_skipped,
        total_errors=total_errors,
    )

    await fetcher.close()
    return results


async def _crawl_department(
    dept: dict[str, Any],
    ports: Ports,
    fetcher: Fetcher,
    mode: CrawlMode,
    options: CrawlOptions,
    logger: Any,
    pipeline: Pipeline,
) -> SourceResult:
    strategy_cls = STRATEGY_MAP.get(dept["strategy"])
    if not strategy_cls:
        raise ValueError(f"Unknown strategy: {dept['strategy']}")

    strategy = strategy_cls(fetcher)
    result = SourceResult(dept_id=dept["id"], dept_name=dept["name"])

    # aclosing makes generator teardown deterministic when run_events
    # raises (accept/flush failure) — without it the suspended generator
    # is finalized at GC time with flaky asyncio warnings.
    async with aclosing(
        iter_source(
            dept, strategy, mode=mode, work_seed=ports.work_seed,
            options=options, logger=logger, pipeline=pipeline,
        )
    ) as events:
        await run_events(events, ports.sink, result=result)

    logger.info(
        "department_crawl_finished",
        dept_id=result.dept_id,
        inserted=result.inserted,
        updated=result.updated,
        skipped=result.skipped,
        errors=result.errors,
        duration_ms=result.duration_ms,
    )
    return result


async def iter_source(
    dept: dict[str, Any],
    strategy: Any,
    *,
    mode: CrawlMode,
    work_seed: WorkSeed,
    options: CrawlOptions,
    logger: Any,
    pipeline: Pipeline = DEFAULT_PIPELINE,
) -> AsyncGenerator[CrawlEvent, None]:
    """The crawl loop as an event stream — no store, no sink, no counters.

    Yields the full vocabulary: write-bearing result events plus the
    progress tier. The consumer (runner) owns aggregation and flush
    semantics. Break positions and log call sites are byte-pinned by the
    characterization goldens — do not reorder.
    """
    logger.info("starting_department_crawl", dept_id=dept["id"], dept_name=dept["name"])
    yield SourceStarted(source_id=dept["id"], source_name=dept["name"])

    # Re-crawl null content — deliberately divergent from the upsert path
    # (위험 ④): explicit field list, no build_notice, no editHistory.
    # Unconditional, mode-independent (adr-006 §⑫).
    null_refs = await work_seed.pending_refs(dept["id"])
    if null_refs:
        logger.info("recrawling_null_content", count=len(null_refs), dept_id=dept["id"])
        for ref in null_refs:
            detail = await strategy.crawl_detail(
                {"articleNo": ref.article_no, "detailPath": ref.detail_path}, dept
            )
            if detail:
                cleaned = clean_html(detail.content, dept["baseUrl"])
                raw_content = normalize_content_urls(detail.content, dept["baseUrl"])
                if cleaned and len(cleaned.encode()) > MAX_CONTENT_BYTES:
                    logger.warning(
                        "oversized_content_dropped",
                        articleNo=ref.article_no,
                        dept=dept["id"],
                        size=len(cleaned.encode()),
                    )
                    cleaned = None
                    raw_content = None
                clean_markdown = html_to_markdown(cleaned)
                yield ContentRefreshed(
                    source_id=dept["id"],
                    ref=ref,
                    fields={
                        "content": raw_content,
                        "contentText": detail.contentText,
                        "cleanHtml": cleaned,
                        "cleanMarkdown": clean_markdown,
                        "contentHash": compute_content_hash(cleaned),
                        "attachments": detail.attachments,
                    },
                )

    # Crawl list pages
    max_pages = options.max_pages or (100 if isinstance(mode, Incremental) else 2500)
    page = 0
    stopped_by = "max_pages"
    source_down = False
    last_error = ""

    while page < max_pages:
        try:
            list_items = await strategy.crawl_list(dept, page)
        except Exception as exc:
            logger.error("list_fetch_failed", dept_id=dept["id"], page=page, error=str(exc))
            yield ListFetchFailed(source_id=dept["id"], page=page, error=str(exc))
            if page == 0:
                # Decided here, surfaced only via SourceFinished — the runner
                # must not infer source_down from ListFetchFailed (a page-3
                # failure is not a downed source).
                source_down = True
                last_error = str(exc)
            stopped_by = "list_fetch_failed"
            break

        if not list_items:
            logger.info("empty_list_page", dept_id=dept["id"], page=page)
            stopped_by = "empty_page"
            break

        is_first_page = page == 0
        below_floor = page_below_floor(list_items, since=options.since_date)

        # Page 0 must be processed even when its regular rows are all below
        # the floor: a pinned row dated after the floor only ever surfaces
        # here, and breaking first would silently drop it forever. Deeper
        # pages repeat the same pinned rows, so breaking pre-process is safe.
        if below_floor and not is_first_page:
            logger.info("floor_date_stopping", page=page, dept_id=dept["id"])
            stopped_by = "floor_date"
            break

        existing_meta: Mapping[int, SeenRecord]
        match mode:
            case Incremental(seen=seen_index):
                article_nos = [item.articleNo for item in list_items]
                existing_meta = await seen_index.lookup(dept["id"], article_nos)
                all_known = not should_continue(list_items, existing_meta)
            case FullSweep():
                # Explicit assignment (not emergent) — kills the latent
                # UnboundLocalError of the v1 skeleton (adr-006 근거 ⑦).
                # No lookup call — matching the old full path's zero DB reads.
                existing_meta, all_known = {}, False
            case _:
                assert_never(mode)

        if not is_first_page and all_known:
            logger.info("all_known_stopping", page=page)
            stopped_by = "all_known"
            break

        if is_first_page and all_known:
            # Logged BEFORE processing — pinned by the round2/round3 golden
            # log_events order (precedes change_detected).
            logger.info("all_known_first_page_early_stop")

        # aclosing on the inner generator too: if iter_source is torn down
        # mid-page, _emit_page is closed deterministically instead of at
        # GC time via the event loop's asyncgen finalizer.
        async with aclosing(
            _emit_page(list_items, existing_meta, strategy, dept, options, logger, pipeline)
        ) as page_events:
            async for ev in page_events:
                yield ev
        yield PageCompleted(source_id=dept["id"], page=page)

        if is_first_page and all_known:
            stopped_by = "all_known_first_page"
            break

        if below_floor:
            logger.info("floor_date_stopping", page=page, dept_id=dept["id"])
            stopped_by = "floor_date"
            break

        page += 1

    yield SourceFinished(
        source_id=dept["id"],
        stopped_by=stopped_by,
        source_down=source_down,
        last_error=last_error,
    )


async def _emit_page(
    list_items: list[NoticeListItem],
    existing_meta: Mapping[int, SeenRecord],
    strategy: Any,
    dept: dict[str, Any],
    options: CrawlOptions,
    logger: Any,
    pipeline: Pipeline,
) -> AsyncGenerator[CrawlEvent, None]:
    """One merged page emitter for both modes: with existing_meta={} every
    item takes the previous-is-None branch — the old full-sweep path falls
    out. Yields events only; storage and counters are the runner's job."""
    for item in list_items:
        try:
            if options.since_date and item.date and item.date < options.since_date:
                # Silent today (no log line) — event only; adding a log here
                # would break the golden log_events byte-identity.
                yield ItemSkipped(
                    source_id=dept["id"],
                    article_no=item.articleNo,
                    reason="below_floor",
                )
                continue

            existing = existing_meta.get(item.articleNo)

            if existing and not has_changed(item, existing):
                yield NoticeUnchanged(
                    source_id=dept["id"],
                    article_no=item.articleNo,
                    views=item.views,
                )
                continue

            detail = await strategy.crawl_detail(
                {"articleNo": item.articleNo, "detailPath": item.detailPath}, dept
            )

            # The content pipeline owns every derived slot (stages.py);
            # image verification runs inside it, before build_notice, so
            # dimensions land in cleanHtml/cleanMarkdown.
            source_url = (
                item.detailPath
                if item.detailPath.startswith("http")
                else f"{dept['baseUrl']}{item.detailPath}"
            )
            doc = await pipeline.run(
                ContentDoc(raw=detail.content if detail else None),
                StageContext(
                    source_id=dept["id"],
                    base_url=dept["baseUrl"],
                    source_url=source_url,
                    article_no=item.articleNo,
                    logger=logger,
                ),
            )

            notice = build_notice(
                item, detail,
                department=dept["name"],
                source_id=dept["id"],
                base_url=dept["baseUrl"],
                content=doc,
            )

            if not existing:
                yield NoticeCrawled(source_id=dept["id"], notice=notice)
            else:
                logger.info(
                    "change_detected",
                    articleNo=item.articleNo,
                    old_title=existing.title,
                    new_title=item.title,
                )
                old_hash = existing.content_hash
                new_hash = notice.contentHash
                change = ChangeInfo(
                    old_hash=old_hash,
                    new_hash=new_hash,
                    old_title=existing.title,
                    new_title=item.title,
                    title_changed=existing.title != item.title,
                    content_changed=old_hash is not None and old_hash != new_hash,
                )
                yield NoticeCrawled(
                    source_id=dept["id"],
                    notice=notice,
                    previous=existing,
                    change=change,
                )

        # Must stay `except Exception` (never broaden): yield points sit
        # inside this try, so aclose()'s GeneratorExit (a BaseException) has
        # to pass through — a broader catch would turn cancellation into a
        # phantom ItemFailed.
        except Exception as exc:
            logger.error("process_article_failed", articleNo=item.articleNo, error=str(exc))
            yield ItemFailed(
                source_id=dept["id"],
                article_no=item.articleNo,
                error=str(exc),
            )

