from __future__ import annotations

import asyncio

import click

from ..shared.db import close_client
from ..shared.logger import configure_logging


@click.command("summarize")
@click.option("--batch-size", type=int, default=50, help="Notices per batch")
@click.option("--delay", type=float, default=1.0, help="Delay between API calls (seconds)")
def summarize_cli(batch_size: int, delay: float) -> None:
    """Run AI summarization on unsummarized notices."""
    from ..shared.config import init_config

    init_config()
    configure_logging()
    asyncio.run(_run(batch_size, delay))


async def _run(batch_size: int, delay: float) -> None:
    from .processor import run_summary_batch

    try:
        await run_summary_batch(batch_size=batch_size, delay_seconds=delay)
    finally:
        await close_client()
