from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ...core.events import ChangeInfo, ContentRefreshed, NoticeCrawled, NoticeUnchanged
from ...core.ports import Outcome, Ports, SeenRecord, Sink, SourceSpec
from ...core.results import SourceResult
from ...shared.db import get_db
from ...shared.fetcher import Fetcher
from ...shared.html_cleaner import clean_html, normalize_content_urls
from ...shared.html_to_markdown import html_to_markdown
from ...shared.logger import get_logger
from .constants import SERVICE_START_DATE
from .policy import has_changed, page_below_floor, should_continue
from .hashing import compute_content_hash
from .image_verifier import ImageCheckResult, verify_notice_images
from .models import NoticeListItem
from .normalizer import build_notice
from .strategies import STRATEGY_MAP


_MAX_CONTENT_BYTES = 5 * 1024 * 1024  # 5MB


@dataclass
class CrawlOptions:
    incremental: bool = True
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
) -> list[SourceResult]:
    crawl_id = uuid.uuid4().hex[:8]
    logger = get_logger("orchestrator", crawl_id=crawl_id)

    if ports is None:
        db = await get_db()
        collection = db["notices"]
        # Lazy wiring import — the single plugins import point. Temporary
        # modules→wiring edge, retired in PR 7 when injection inverts.
        from ...wiring import build_notices_ports

        ports = build_notices_ports(collection)

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

    if not filtered:
        logger.warning("no_matching_departments", dept_filter=options.dept_filter)
        return []

    for dept in filtered:
        await ports.sink.prepare(SourceSpec(source_id=dept["id"], name=dept["name"]))

    sem = asyncio.Semaphore(5)
    results: list[SourceResult] = []

    async def crawl_with_sem(dept: dict) -> SourceResult:
        async with sem:
            return await _crawl_department(dept, ports, fetcher, options, logger)

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
    options: CrawlOptions,
    logger: Any,
) -> SourceResult:
    start = time.monotonic()
    strategy_cls = STRATEGY_MAP.get(dept["strategy"])
    if not strategy_cls:
        raise ValueError(f"Unknown strategy: {dept['strategy']}")

    strategy = strategy_cls(fetcher)
    result = SourceResult(dept_id=dept["id"], dept_name=dept["name"])

    logger.info("starting_department_crawl", dept_id=dept["id"], dept_name=dept["name"])

    # Re-crawl null content — deliberately divergent from the upsert path
    # (위험 ④): explicit field list, no build_notice, no editHistory.
    null_refs = await ports.work_seed.pending_refs(dept["id"])
    if null_refs:
        logger.info("recrawling_null_content", count=len(null_refs), dept_id=dept["id"])
        for ref in null_refs:
            detail = await strategy.crawl_detail(
                {"articleNo": ref.article_no, "detailPath": ref.detail_path}, dept
            )
            if detail:
                cleaned = clean_html(detail.content, dept["baseUrl"])
                raw_content = normalize_content_urls(detail.content, dept["baseUrl"])
                if cleaned and len(cleaned.encode()) > _MAX_CONTENT_BYTES:
                    logger.warning(
                        "oversized_content_dropped",
                        articleNo=ref.article_no,
                        dept=dept["id"],
                        size=len(cleaned.encode()),
                    )
                    cleaned = None
                    raw_content = None
                clean_markdown = html_to_markdown(cleaned)
                await ports.sink.accept(
                    ContentRefreshed(
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
                )
                result.updated += 1

    # Crawl list pages
    max_pages = options.max_pages or (100 if options.incremental else 2500)
    page = 0

    while page < max_pages:
        try:
            list_items = await strategy.crawl_list(dept, page)
        except Exception as exc:
            logger.error("list_fetch_failed", dept_id=dept["id"], page=page, error=str(exc))
            result.errors += 1
            if page == 0:
                result.source_down = True
                result.last_error = str(exc)
            break

        if not list_items:
            logger.info("empty_list_page", dept_id=dept["id"], page=page)
            break

        is_first_page = page == 0
        below_floor = page_below_floor(list_items, since=options.since_date)

        # Page 0 must be processed even when its regular rows are all below
        # the floor: a pinned row dated after the floor only ever surfaces
        # here, and breaking first would silently drop it forever. Deeper
        # pages repeat the same pinned rows, so breaking pre-process is safe.
        if below_floor and not is_first_page:
            logger.info("floor_date_stopping", page=page, dept_id=dept["id"])
            break

        if options.incremental:
            article_nos = [item.articleNo for item in list_items]
            existing_meta = await ports.seen.lookup(dept["id"], article_nos)
            all_known = not should_continue(list_items, existing_meta)
        else:
            # Explicit assignment (not emergent) — kills the latent
            # UnboundLocalError of the v1 skeleton (adr-006 근거 ⑦).
            existing_meta, all_known = {}, False

        if not is_first_page and all_known:
            logger.info("all_known_stopping", page=page)
            break

        if is_first_page and all_known:
            # Logged BEFORE processing — pinned by the round2/round3 golden
            # log_events order (precedes change_detected).
            logger.info("all_known_first_page_early_stop")

        await _process_page(
            list_items, existing_meta, strategy, dept, options, ports.sink, result, logger
        )

        if is_first_page and all_known:
            break

        if below_floor:
            logger.info("floor_date_stopping", page=page, dept_id=dept["id"])
            break

        page += 1

    result.duration_ms = int((time.monotonic() - start) * 1000)
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


async def _verify_and_measure_images(
    content_html: str | None,
    source_url: str,
    dept_id: str,
    article_no: int,
    logger: Any,
) -> ImageCheckResult:
    """Best-effort image verification + dimension detection. Never raises."""
    try:
        result = await verify_notice_images(content_html, source_url)
        if result.broken:
            logger.warning(
                "broken_notice_images",
                articleNo=article_no,
                dept_id=dept_id,
                checked=result.checked,
                broken_count=len(result.broken),
                broken=result.broken[:5],  # cap log payload
            )
        if result.dimensions:
            logger.debug(
                "image_dimensions_detected",
                articleNo=article_no,
                count=len(result.dimensions),
            )
        return result
    except Exception as exc:
        logger.warning(
            "image_verify_failed",
            articleNo=article_no,
            dept_id=dept_id,
            error=str(exc),
        )
        return ImageCheckResult()


async def _process_page(
    list_items: list[NoticeListItem],
    existing_meta: Mapping[int, SeenRecord],
    strategy: Any,
    dept: dict[str, Any],
    options: CrawlOptions,
    sink: Sink,
    result: SourceResult,
    logger: Any,
) -> None:
    """One merged processor for both modes: with existing_meta={} every item
    takes the previous-is-None branch — the old full-sweep path falls out."""
    for item in list_items:
        try:
            if options.since_date and item.date and item.date < options.since_date:
                result.skipped += 1
                continue

            existing = existing_meta.get(item.articleNo)

            if existing and not has_changed(item, existing):
                await sink.accept(
                    NoticeUnchanged(
                        source_id=dept["id"],
                        article_no=item.articleNo,
                        views=item.views,
                    )
                )
                result.skipped += 1
                continue

            detail = await strategy.crawl_detail(
                {"articleNo": item.articleNo, "detailPath": item.detailPath}, dept
            )

            # Verify images + detect dimensions before build_notice so
            # dimensions can be injected into cleanHtml/cleanMarkdown.
            abs_content = (
                normalize_content_urls(detail.content, dept["baseUrl"])
                if detail and detail.content
                else None
            )
            source_url = (
                item.detailPath
                if item.detailPath.startswith("http")
                else f"{dept['baseUrl']}{item.detailPath}"
            )
            img_result = await _verify_and_measure_images(
                abs_content, source_url, dept["id"], item.articleNo, logger,
            )

            notice = build_notice(
                item, detail,
                department=dept["name"],
                source_id=dept["id"],
                base_url=dept["baseUrl"],
                image_dimensions=img_result.dimensions or None,
            )

            if not existing:
                outcome = await sink.accept(
                    NoticeCrawled(source_id=dept["id"], notice=notice)
                )
                # None ⇒ INSERTED (architecture §러너 집계 규칙).
                if outcome is Outcome.UPDATED:
                    result.updated += 1
                else:
                    result.inserted += 1
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
                await sink.accept(
                    NoticeCrawled(
                        source_id=dept["id"],
                        notice=notice,
                        previous=existing,
                        change=change,
                    )
                )
                result.updated += 1

        except Exception as exc:
            logger.error("process_article_failed", articleNo=item.articleNo, error=str(exc))
            result.errors += 1

    await sink.flush()

