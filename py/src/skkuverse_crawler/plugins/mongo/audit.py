"""Database scans that drive the notice validators.

The checks themselves are pure and live in
``modules/notices/validation.py``; what belongs here is the part that is
actually Mongo-shaped — building the query, walking the cursor,
aggregating a report. Same plugins→modules direction as update_checker.

``get_db`` and the source loader stay lazy inside the functions: that is
what lets the tests patch them and what keeps importing this module free
of a database connection.
"""

from __future__ import annotations

import asyncio

import httpx

from ...modules.notices.validation import (
    _BROWSER_UA,
    _TIMEOUT,
    GNUBOARD_STRATEGIES,
    AttachmentIssue,
    MarkdownValidationReport,
    NoticeMarkdownResult,
    NoticeValidationResult,
    ValidationReport,
    check_reachability,
    validate_notice_attachments,
    validate_notice_markdown,
)
from ...shared.logger import get_logger

logger = get_logger("notices_audit")


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


async def validate_attachments(
    *,
    dept_filter: tuple[str, ...] | None = None,
    limit: int | None = None,
    check_http: bool = True,
    http_concurrency: int = 20,
) -> ValidationReport:
    """Scan notices in MongoDB and validate their attachments.

    Parameters
    ----------
    dept_filter:
        Restrict to specific ``sourceId`` values.
    limit:
        Max notices to scan.
    check_http:
        When True, perform HEAD requests on non-gnuboard URLs.
    http_concurrency:
        Max concurrent HTTP requests.
    """
    from ...shared.db import get_db
    from ...modules.notices.config.loader import load_and_validate

    departments = load_and_validate()
    strategy_map: dict[str, str] = {
        dept["id"]: dept["strategy"] for dept in departments
    }

    db = await get_db()
    collection = db["notices"]

    query: dict = {"attachments": {"$exists": True, "$ne": []}}
    if dept_filter:
        query["sourceId"] = {"$in": list(dept_filter)}

    report = ValidationReport()
    semaphore = asyncio.Semaphore(http_concurrency)

    client: httpx.AsyncClient | None = None
    if check_http:
        client = httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _BROWSER_UA})

    try:
        cursor = collection.find(query)
        if limit:
            cursor = cursor.limit(limit)

        count = 0
        async for doc in cursor:
            count += 1
            attachments: list[dict[str, str]] = doc.get("attachments", [])
            dept_id = doc.get("sourceId", "")
            source_url = doc.get("sourceUrl", "")
            article_no = doc.get("articleNo", 0)
            notice_id = str(doc["_id"])

            strategy = strategy_map.get(dept_id)
            if strategy is None:
                logger.warning("unknown_dept", sourceId=dept_id, notice_id=notice_id)

            report.total_notices += 1
            report.total_attachments += len(attachments)

            # Sync checks
            issues = validate_notice_attachments(attachments, strategy)

            # Async HTTP checks (non-gnuboard only)
            is_gnuboard = strategy in GNUBOARD_STRATEGIES
            if check_http and client is not None and not is_gnuboard:
                http_tasks = []
                for i, att in enumerate(attachments):
                    att_url = att.get("url", "")
                    if not att_url.startswith(("http://", "https://")):
                        continue  # scheme check already flagged
                    http_tasks.append(check_reachability(
                        att_url, source_url, client, semaphore, i, att.get("name", ""),
                    ))
                if http_tasks:
                    results = await asyncio.gather(*http_tasks, return_exceptions=True)
                    for r in results:
                        if isinstance(r, AttachmentIssue):
                            issues.append(r)
                        elif isinstance(r, Exception):
                            logger.warning("http_check_exception", error=str(r))
            elif is_gnuboard:
                report.skipped_http_checks += len(attachments)

            if issues:
                report.notices_with_issues += 1
                for issue in issues:
                    report.issue_counts[issue.check] += 1
                report.results.append(NoticeValidationResult(
                    notice_id=notice_id,
                    article_no=article_no,
                    source_id=dept_id,
                    source_url=source_url,
                    issues=issues,
                ))

            if count % 200 == 0:
                logger.info("validation_progress", scanned=count)

    finally:
        if client is not None:
            await client.aclose()

    logger.info(
        "validation_complete",
        total=report.total_notices,
        issues=report.notices_with_issues,
    )
    return report


# ---------------------------------------------------------------------------
# Async DB orchestrator
# ---------------------------------------------------------------------------


async def validate_markdown(
    *,
    dept_filter: tuple[str, ...] | None = None,
    limit: int | None = None,
    min_severity: str = "warning",
) -> MarkdownValidationReport:
    """Scan notices in MongoDB and validate their cleanMarkdown fields.

    Parameters
    ----------
    dept_filter:
        Restrict to specific ``sourceId`` values.
    limit:
        Max notices to scan.
    min_severity:
        ``"warning"`` (default) or ``"error"``.
    """
    from ...shared.db import get_db

    db = await get_db()
    collection = db["notices"]

    query: dict = {"cleanMarkdown": {"$exists": True, "$ne": None}}
    if dept_filter:
        query["sourceId"] = {"$in": list(dept_filter)}

    report = MarkdownValidationReport()

    cursor = collection.find(
        query,
        {"cleanMarkdown": 1, "articleNo": 1, "sourceId": 1, "sourceUrl": 1},
    )
    if limit:
        cursor = cursor.limit(limit)

    count = 0
    async for doc in cursor:
        count += 1
        md = doc.get("cleanMarkdown", "")
        notice_id = str(doc["_id"])

        report.total_notices += 1

        issues = validate_notice_markdown(md, min_severity=min_severity)

        if issues:
            report.notices_with_issues += 1
            for issue in issues:
                report.issue_counts[issue.check] += 1
            report.results.append(NoticeMarkdownResult(
                notice_id=notice_id,
                article_no=doc.get("articleNo", 0),
                source_id=doc.get("sourceId", ""),
                source_url=doc.get("sourceUrl", ""),
                issues=issues,
            ))

        if count % 200 == 0:
            logger.info("validation_progress", scanned=count)

    logger.info(
        "validation_complete",
        total=report.total_notices,
        issues=report.notices_with_issues,
    )
    return report
