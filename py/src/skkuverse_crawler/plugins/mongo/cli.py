"""CLI entry points for the Mongo-backed scans.

Assembly leaves: a CLI command's job is to build the world and call in,
so importing plugins here is the sanctioned direction (adr-006 invariant
as amended in PR 7). The commands that live here are the ones whose work
IS a store scan — they moved out of modules/notices with their drivers.
"""

from __future__ import annotations

import asyncio
import json as _json
import sys
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
    from ...env import init_config

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
    from ...env import init_config

    cfg = init_config()
    # Same rule as `notices --json`: when stdout carries the report, logs go
    # to stderr or the output is not parseable.
    configure_logging(cfg, stream=sys.stderr if json_output else None)
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
    from ...env import init_config

    cfg = init_config()
    configure_logging(cfg, stream=sys.stderr if json_output else None)
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


# ── repair-dimensions ─────────────────────────────────


@click.command("repair-dimensions")
@click.option("--source", "dept", multiple=True, help="Department ID(s) to repair")
@click.option("--limit", type=int, default=None, help="Max notices to scan")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option(
    "--apply",
    is_flag=True,
    help="Write the repairs. Without it this only reports what it would change.",
)
def repair_dimensions_cli(
    dept: tuple[str, ...],
    limit: int | None,
    json_output: bool,
    apply: bool,
) -> None:
    """Repair notices Tier-2 wrote before it ran the content pipeline."""
    from ...env import init_config

    cfg = init_config()
    configure_logging(cfg, stream=sys.stderr if json_output else None)
    asyncio.run(_run_repair_dimensions(dept, limit, json_output, apply))


async def _run_repair_dimensions(
    dept_filter: tuple[str, ...],
    limit: int | None,
    json_output: bool,
    apply: bool,
) -> None:
    from ...shared.db import close_client

    try:
        from .repair import repair_lost_dimensions

        report = await repair_lost_dimensions(
            dept_filter=dept_filter if dept_filter else None,
            limit=limit,
            apply=apply,
        )
        if json_output:
            print(_json.dumps(asdict(report), ensure_ascii=False, indent=2))
        else:
            _print_repair_report(report, apply)
    finally:
        await close_client()


def _print_repair_report(report, apply: bool) -> None:
    verb = "Repaired" if apply else "Would repair"
    print()
    print("=" * 60)
    print(f"  Dimension repair — {'APPLIED' if apply else 'DRY RUN'}")
    print("=" * 60)
    print(f"  Scanned            : {report.scanned}")
    print(f"  {verb:<19}: {report.repaired}")
    print(f"  Already consistent : {report.already_consistent}")
    print(f"  No stored body     : {report.skipped_no_content}")
    # Counted across all of the above, not inside any of them: a document
    # with no stored measurement may still have had its text or hash
    # repaired. Indenting it under one line said otherwise.
    print(f"  Images with no stored measurement (any outcome): {report.unmeasurable}")
    if report.changed_fields:
        print("  Fields:")
        for name, count in sorted(report.changed_fields.items()):
            print(f"    {name:<16} {count}")
    if report.samples:
        print("  Samples:")
        for s in report.samples:
            fields = ", ".join(s["fields"])
            print(
                f"    [{s['sourceId']}] articleNo={s['articleNo']} "
                f"dims={s['restored_dimensions']} → {fields}"
            )
    if not apply and report.repaired:
        print()
        print("  Re-run with --apply to write these.")
    print()

# ── repair-attachments ────────────────────────────────


@click.command("repair-attachments")
@click.option("--source", "dept", multiple=True, help="Department ID(s) to repair")
@click.option("--limit", type=int, default=None, help="Max notices to scan")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option(
    "--apply",
    is_flag=True,
    help="Write the repairs. Without it this only reports what it would change.",
)
@click.option(
    "--refetch",
    is_flag=True,
    help=(
        "Re-read every notice's detail page instead of repairing from stored "
        "data. Needed only to drop attachments the source has deleted."
    ),
)
def repair_attachments_cli(
    dept: tuple[str, ...],
    limit: int | None,
    json_output: bool,
    apply: bool,
    refetch: bool,
) -> None:
    """Repair attachment links stored without a referer or with a stale id."""
    from ...env import init_config

    cfg = init_config()
    configure_logging(cfg, stream=sys.stderr if json_output else None)
    asyncio.run(_run_repair_attachments(dept, limit, json_output, apply, refetch))


async def _run_repair_attachments(
    dept_filter: tuple[str, ...],
    limit: int | None,
    json_output: bool,
    apply: bool,
    refetch: bool = False,
) -> None:
    from ...shared.db import close_client

    try:
        from .repair_attachments import repair_attachments

        report = await repair_attachments(
            dept_filter=dept_filter if dept_filter else None,
            limit=limit,
            apply=apply,
            force_refetch=refetch,
        )
        if json_output:
            print(_json.dumps(asdict(report), ensure_ascii=False, indent=2))
        else:
            _print_attachment_repair_report(report, apply)
    finally:
        await close_client()


def _print_attachment_repair_report(report, apply: bool) -> None:
    verb = "Repaired" if apply else "Would repair"
    print()
    print("=" * 60)
    print(f"  Attachment repair — {'APPLIED' if apply else 'DRY RUN'}")
    print("=" * 60)
    print(f"  Scanned            : {report.scanned}")
    print(f"  {verb:<19}: {report.repaired}")
    print(f"  Already consistent : {report.already_consistent}")
    # Its own line because it is neither repaired nor consistent: the notice
    # could not be read, so nothing is known about it either way.
    print(f"  Could not refetch  : {report.unfetchable}")
    if report.by_source:
        print("  By source:")
        for name, count in sorted(report.by_source.items()):
            print(f"    {name:<20} {count}")
    if report.samples:
        print("  Samples:")
        for s in report.samples:
            print(f"    [{s['sourceId']}] articleNo={s['articleNo']}")
            for label in ("before", "after"):
                for att in s[label]:
                    ref = " +referer" if att.get("referer") else ""
                    print(f"      {label:<7} {att.get('name', '')[:40]}{ref}")
    if not apply and report.repaired:
        print()
        print("  Re-run with --apply to write these.")
    print()
