from __future__ import annotations

import asyncio

import click

from .shared.logger import configure_logging


@click.group()
def main() -> None:
    """skkuverse-crawler: Multi-module SKKU data crawler."""
    pass


@main.command()
@click.option("--module", "-m", default=None, help="Run specific module only")
def start(module: str | None) -> None:
    """Start the cron scheduler for all (or one) module."""
    from .shared.config import init_config

    cfg = init_config()
    configure_logging(cfg)
    asyncio.run(_start_scheduler(module))


async def _start_scheduler(module_filter: str | None = None) -> None:
    from .plugins.scheduler.runner import run_scheduler
    from .shared.db import close_client
    from .wiring import build_runtime

    modules = build_runtime()
    await run_scheduler(modules, module_filter=module_filter, on_shutdown=close_client)


# Register CLI subcommands
from .plugins.health.cli import health_summary_cli  # noqa: E402
from .modules.notices.cli import notices_cli  # noqa: E402
from .plugins.ai_summary.cli import summarize_cli  # noqa: E402
from .plugins.mongo.cli import update_check_cli, validate_attachments_cli, validate_markdown_cli  # noqa: E402
main.add_command(notices_cli)
main.add_command(update_check_cli)
main.add_command(validate_attachments_cli)
main.add_command(validate_markdown_cli)
main.add_command(summarize_cli)
main.add_command(health_summary_cli)
