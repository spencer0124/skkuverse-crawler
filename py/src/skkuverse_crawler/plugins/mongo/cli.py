"""CLI entry points for the Mongo-backed scans.

Assembly leaves: a CLI command's job is to build the world and call in,
so importing plugins here is the sanctioned direction (adr-006 invariant
as amended in PR 7). The commands that live here are the ones whose work
IS a store scan — they moved out of modules/notices with their drivers.
"""

from __future__ import annotations

import asyncio

import click

from ...shared.db import close_client
from ...shared.logger import configure_logging
from .update_checker import run_update_check


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

    departments = load_and_validate()

    try:
        await run_update_check(
            departments,
            window_days=window_days,
            dept_filter=dept_filter if dept_filter else None,
        )
    finally:
        await close_client()
