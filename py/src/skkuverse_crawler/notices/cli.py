from __future__ import annotations

import asyncio
import json as _json
from dataclasses import asdict
from typing import TYPE_CHECKING

import click

from ..shared.db import close_client
from ..shared.logger import configure_logging
from .backfill import run as run_backfill
from .config.loader import load_and_validate
from .orchestrator import CrawlOptions, run_crawl
from .update_checker import run_update_check

if TYPE_CHECKING:
    from .attachment_validator import ValidationReport
    from .markdown_validator import MarkdownValidationReport


@click.command("notices")
@click.option("--once", is_flag=True, help="Run once and exit")
@click.option("--all", "full_crawl", is_flag=True, help="Full (non-incremental) crawl")
@click.option("--dept", multiple=True, help="Department ID(s) to crawl")
@click.option("--pages", type=int, default=None, help="Max pages per department")
@click.option("--delay", type=int, default=500, help="Delay between requests (ms)")
def notices_cli(once: bool, full_crawl: bool, dept: tuple[str, ...], pages: int | None, delay: int) -> None:
    """Run the notices crawler."""
    from ..shared.config import init_config

    init_config()
    configure_logging()
    asyncio.run(_run(once, full_crawl, dept, pages, delay))


async def _run(
    once: bool,
    full_crawl: bool,
    dept_filter: tuple[str, ...],
    max_pages: int | None,
    delay_ms: int,
) -> None:
    departments = load_and_validate()

    options = CrawlOptions(
        incremental=not full_crawl,
        max_pages=max_pages,
        delay_ms=delay_ms,
        dept_filter=dept_filter if dept_filter else None,
    )

    try:
        await run_crawl(departments, options)
    finally:
        await close_client()


@click.command("update-check")
@click.option("--days", type=int, default=14, help="Window in days (default: 14)")
@click.option("--dept", multiple=True, help="Department ID(s) to check")
def update_check_cli(days: int, dept: tuple[str, ...]) -> None:
    """Run Tier 2 update detection on recent notices."""
    from ..shared.config import init_config

    init_config()
    configure_logging()
    asyncio.run(_run_update_check(days, dept))


async def _run_update_check(
    window_days: int,
    dept_filter: tuple[str, ...],
) -> None:
    departments = load_and_validate()

    try:
        await run_update_check(
            departments,
            window_days=window_days,
            dept_filter=dept_filter if dept_filter else None,
        )
    finally:
        await close_client()


@click.command("backfill-content")
@click.option("--apply", is_flag=True, help="Actually update documents (default: dry-run)")
@click.option("--dept", multiple=True, help="Restrict to specific sourceDeptId(s)")
@click.option("--limit", type=int, default=None, help="Stop after N documents")
def backfill_content_cli(apply: bool, dept: tuple[str, ...], limit: int | None) -> None:
    """Rebuild cleanHtml/contentText/cleanMarkdown from stored `content` field.

    Re-runs clean_html + html_to_markdown on existing notices so pipeline
    improvements apply retroactively. Dry-run by default.
    """
    import sys

    configure_logging()
    sys.exit(asyncio.run(run_backfill(
        apply=apply,
        dept_filter=dept if dept else None,
        limit=limit,
    )))


@click.command("backfill-attachment-referer")
@click.option("--apply", is_flag=True, help="Actually update documents (default: dry-run)")
@click.option("--dept", multiple=True, help="Restrict to specific sourceDeptId(s)")
@click.option("--limit", type=int, default=None, help="Stop after N documents")
def backfill_attachment_referer_cli(apply: bool, dept: tuple[str, ...], limit: int | None) -> None:
    """Add referer field to gnuboard attachment metadata.

    Adds the detail-page URL as `referer` so the server proxy can
    establish a PHP session before downloading. No HTTP requests.
    """
    import sys

    from .backfill_attachment_referer import run as run_backfill_referer

    configure_logging()
    sys.exit(asyncio.run(run_backfill_referer(
        apply=apply,
        dept_filter=dept if dept else None,
        limit=limit,
    )))


@click.command("backfill-attachments")
@click.option("--apply", is_flag=True, help="Actually update documents (default: dry-run)")
@click.option("--dept", multiple=True, help="Restrict to specific sourceDeptId(s)")
@click.option("--limit", type=int, default=None, help="Stop after N documents")
def backfill_attachments_cli(apply: bool, dept: tuple[str, ...], limit: int | None) -> None:
    """Re-fetch detail pages to backfill missing attachments.

    Targets skku-standard subdomain departments whose attachments were
    not captured due to a selector mismatch. Dry-run by default.
    """
    import sys

    from .backfill_attachments import run as run_backfill_att

    configure_logging()
    sys.exit(asyncio.run(run_backfill_att(
        apply=apply,
        dept_filter=dept if dept else None,
        limit=limit,
    )))


@click.command("backfill-wpdm-attachments")
@click.option("--apply", is_flag=True, help="Actually update documents (default: dry-run)")
@click.option("--limit", type=int, default=None, help="Stop after N documents")
def backfill_wpdm_cli(apply: bool, limit: int | None) -> None:
    """Re-fetch cheme WPDM posts to fix attachment download URLs.

    Replaces landing-page URLs (/download/slug/) with actual download
    URLs (?wpdmdl=id) by re-fetching from the WP REST API.
    """
    import sys

    from .backfill_wpdm_attachments import run as run_backfill_wpdm

    configure_logging()
    sys.exit(asyncio.run(run_backfill_wpdm(apply=apply, limit=limit)))


@click.command("validate-attachments")
@click.option("--dept", multiple=True, help="Department ID(s) to validate")
@click.option("--limit", type=int, default=None, help="Max notices to scan")
@click.option("--no-http", is_flag=True, help="Skip HTTP reachability checks")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option("--concurrency", type=int, default=20, help="Max concurrent HTTP checks")
def validate_attachments_cli(
    dept: tuple[str, ...],
    limit: int | None,
    no_http: bool,
    json_output: bool,
    concurrency: int,
) -> None:
    """Validate attachment metadata in the notices collection."""
    from ..shared.config import init_config

    init_config()
    configure_logging()
    asyncio.run(_run_validate_attachments(dept, limit, no_http, json_output, concurrency))


async def _run_validate_attachments(
    dept_filter: tuple[str, ...],
    limit: int | None,
    no_http: bool,
    json_output: bool,
    concurrency: int,
) -> None:
    try:
        from .attachment_validator import validate_attachments

        report = await validate_attachments(
            dept_filter=dept_filter if dept_filter else None,
            limit=limit,
            check_http=not no_http,
            http_concurrency=concurrency,
        )
    finally:
        await close_client()

    if json_output:
        _print_json(report)
    else:
        _print_human(report)


def _print_json(report: "ValidationReport") -> None:
    print(_json.dumps(asdict(report), indent=2, ensure_ascii=False, default=str))


def _print_human(report: "ValidationReport") -> None:
    print()
    print("Attachment Validation Report")
    print("=" * 40)
    print(f"  Notices scanned:      {report.total_notices:,}")
    print(f"  Attachments checked:  {report.total_attachments:,}")
    print(f"  Notices with issues:  {report.notices_with_issues:,}")
    print(f"  HTTP checks skipped:  {report.skipped_http_checks:,} (gnuboard)")
    print()

    if report.issue_counts:
        print("Issues by type:")
        for check_type, count in sorted(report.issue_counts.items()):
            print(f"  {check_type:20s} {count:,}")
        print()

    if report.results:
        print(f"Details ({len(report.results)} notices):")
        for r in report.results:
            print(f"  [{r.source_dept_id}] articleNo={r.article_no}  {r.source_url}")
            for issue in r.issues:
                print(f"    [{issue.attachment_index}] {issue.check}: {issue.detail}")
        print()


# ── validate-markdown ─────────────────────────────────


@click.command("validate-markdown")
@click.option("--dept", multiple=True, help="Department ID(s) to validate")
@click.option("--limit", type=int, default=None, help="Max notices to scan")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option(
    "--severity",
    type=click.Choice(["all", "error", "warning"]),
    default="all",
    help="Filter by minimum severity level",
)
def validate_markdown_cli(
    dept: tuple[str, ...],
    limit: int | None,
    json_output: bool,
    severity: str,
) -> None:
    """Validate markdown rendering in stored cleanMarkdown fields."""
    from ..shared.config import init_config

    init_config()
    configure_logging()
    asyncio.run(_run_validate_markdown(dept, limit, json_output, severity))


async def _run_validate_markdown(
    dept_filter: tuple[str, ...],
    limit: int | None,
    json_output: bool,
    severity: str,
) -> None:
    try:
        from .markdown_validator import validate_markdown

        min_severity = "error" if severity == "error" else "warning"
        report = await validate_markdown(
            dept_filter=dept_filter if dept_filter else None,
            limit=limit,
            min_severity=min_severity,
        )
    finally:
        await close_client()

    if json_output:
        _print_md_json(report)
    else:
        _print_md_human(report)


def _print_md_json(report: "MarkdownValidationReport") -> None:
    from dataclasses import asdict

    print(_json.dumps(asdict(report), indent=2, ensure_ascii=False, default=str))


def _print_md_human(report: "MarkdownValidationReport") -> None:
    print()
    print("Markdown Validation Report")
    print("=" * 40)
    print(f"  Notices scanned:      {report.total_notices:,}")
    print(f"  Notices with issues:  {report.notices_with_issues:,}")
    print()

    if report.issue_counts:
        print("Issues by type:")
        for check_type, count in sorted(report.issue_counts.items(), key=lambda x: -x[1]):
            print(f"  {check_type:35s} {count:,}")
        print()

    if report.results:
        print(f"Details ({len(report.results)} notices):")
        for r in report.results:
            print(f"\n  [{r.source_dept_id}] articleNo={r.article_no}")
            print(f"  {r.source_url}")
            for issue in r.issues:
                severity_tag = "ERR" if issue.severity == "error" else "WRN"
                print(f"    L{issue.line} [{severity_tag}] {issue.check}: {issue.detail}")
                if issue.snippet:
                    visible = issue.snippet.replace("\n", "\\n")
                    print(f"      | {visible}")
        print()
