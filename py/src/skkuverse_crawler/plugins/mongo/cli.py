"""CLI entry points for the Mongo-backed scans.

Assembly leaves: a CLI command's job is to build the world and call in,
so importing plugins here is the sanctioned direction (adr-006 invariant
as amended in PR 7). The commands that live here are the ones whose work
IS a store scan — they moved out of modules/notices with their drivers.
"""

from __future__ import annotations

import asyncio
import json as _json
from dataclasses import asdict
from typing import TYPE_CHECKING

import click

from ...shared.logger import configure_logging

if TYPE_CHECKING:
    from ...modules.notices.validation import (
        MarkdownValidationReport,
        ValidationReport,
    )


@click.command("update-check")
@click.option("--days", type=int, default=14, help="Window in days (default: 14)")
@click.option("--source", "dept", multiple=True, help="Department ID(s) to check")
def update_check_cli(days: int, dept: tuple[str, ...]) -> None:
    """Run Tier 2 update detection on recent notices."""
    from ...shared.config import init_config

    cfg = init_config()
    configure_logging(cfg)
    asyncio.run(_run_update_check(days, dept))


async def _run_update_check(
    window_days: int,
    dept_filter: tuple[str, ...],
) -> None:
    from ...modules.notices.config.loader import load_and_validate
    from ...shared.db import close_client
    from .update_checker import run_update_check

    departments = load_and_validate()

    try:
        await run_update_check(
            departments,
            window_days=window_days,
            dept_filter=dept_filter if dept_filter else None,
        )
    finally:
        await close_client()


@click.command("validate-attachments")
@click.option("--source", "dept", multiple=True, help="Department ID(s) to validate")
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
    from ...shared.config import init_config

    cfg = init_config()
    configure_logging(cfg)
    asyncio.run(_run_validate_attachments(dept, limit, no_http, json_output, concurrency))


async def _run_validate_attachments(
    dept_filter: tuple[str, ...],
    limit: int | None,
    no_http: bool,
    json_output: bool,
    concurrency: int,
) -> None:
    from ...shared.db import close_client

    try:
        from .audit import validate_attachments

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
            print(f"  [{r.source_id}] articleNo={r.article_no}  {r.source_url}")
            for issue in r.issues:
                print(f"    [{issue.attachment_index}] {issue.check}: {issue.detail}")
        print()


# ── validate-markdown ─────────────────────────────────


@click.command("validate-markdown")
@click.option("--source", "dept", multiple=True, help="Department ID(s) to validate")
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
    from ...shared.config import init_config

    cfg = init_config()
    configure_logging(cfg)
    asyncio.run(_run_validate_markdown(dept, limit, json_output, severity))


async def _run_validate_markdown(
    dept_filter: tuple[str, ...],
    limit: int | None,
    json_output: bool,
    severity: str,
) -> None:
    from ...shared.db import close_client

    try:
        from .audit import validate_markdown

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
            print(f"\n  [{r.source_id}] articleNo={r.article_no}")
            print(f"  {r.source_url}")
            for issue in r.issues:
                severity_tag = "ERR" if issue.severity == "error" else "WRN"
                print(f"    L{issue.line} [{severity_tag}] {issue.check}: {issue.detail}")
                if issue.snippet:
                    visible = issue.snippet.replace("\n", "\\n")
                    print(f"      | {visible}")
        print()
