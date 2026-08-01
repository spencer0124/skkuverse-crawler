from __future__ import annotations

import asyncio
import importlib

import click

from .shared.logger import configure_logging

# name -> (module, attribute, help text, extras needed to import it)
#
# The help text is duplicated from each command's docstring so that
# `--help` can be rendered without importing anything. Duplication is
# guarded, not trusted: tests/cli/test_lazy_group.py imports every entry
# and asserts the text still matches.
_LAZY: dict[str, tuple[str, str, str, str | None]] = {
    "health-summary": (
        ".plugins.health.cli", "health_summary_cli",
        "Send the daily crawl-health summary to Discord once.", "discord",
    ),
    "notices": (
        ".modules.notices.cli", "notices_cli",
        "Run the notices crawler.", None,
    ),
    "summarize": (
        ".plugins.ai_summary.cli", "summarize_cli",
        "Run AI summarization on unsummarized notices.", "ai",
    ),
    "update-check": (
        ".plugins.mongo.cli", "update_check_cli",
        "Run Tier 2 update detection on recent notices.", "mongo",
    ),
    "validate-attachments": (
        ".plugins.mongo.cli", "validate_attachments_cli",
        "Validate attachment metadata in the notices collection.", "mongo",
    ),
    "validate-markdown": (
        ".plugins.mongo.cli", "validate_markdown_cli",
        "Validate markdown rendering in stored cleanMarkdown fields.", "mongo",
    ),
}


class _LazyGroup(click.Group):
    """Subcommands are imported when invoked, not when the group is built.

    ``format_commands`` is overridden as well, not just ``get_command``:
    click's Group.format_commands calls get_command() for EVERY name in
    list_commands() to render short help, so ``--help`` is precisely the
    path that would materialize every subcommand. Placeholder Commands
    carry the table's help text through click's own get_short_help_str(),
    which keeps the rendering byte-identical to an eager group instead of
    re-implementing its truncation.

    ``importlib`` is the one module-level import that breaks the codebase's
    "plain from x import y" idiom, and it has to be: a lazy *group* cannot
    be written with static imports.
    """

    def list_commands(self, ctx: click.Context) -> list[str]:
        return sorted({*super().list_commands(ctx), *_LAZY})

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        meta = _LAZY.get(cmd_name)
        if meta is None:
            return super().get_command(ctx, cmd_name)
        module, attr, _help, extras = meta
        try:
            loaded = importlib.import_module(module, __package__)
        except ImportError as exc:
            if extras is None:
                raise
            # Without this, a core-only install answers `update-check` with
            # a bare ModuleNotFoundError from four frames down.
            raise click.ClickException(
                f"`{cmd_name}` needs the optional `{extras}` dependencies — install with:\n"
                f"    pip install 'skkuverse-crawler[{extras}]'\n"
                f"({exc})"
            ) from exc
        return getattr(loaded, attr)

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        rows: list[tuple[str, click.Command]] = [
            (name, click.Command(name, help=meta[2])) for name, meta in _LAZY.items()
        ]
        rows += list(self.commands.items())
        rows.sort()
        limit = formatter.width - 6 - max(len(name) for name, _ in rows)
        with formatter.section("Commands"):
            formatter.write_dl([(name, cmd.get_short_help_str(limit)) for name, cmd in rows])


@click.group(cls=_LazyGroup)
def main() -> None:
    """skkuverse-crawler: Multi-module SKKU data crawler."""
    pass


@main.command()
@click.option("--module", "-m", default=None, help="Run specific module only")
def start(module: str | None) -> None:
    """Start the cron scheduler for all (or one) module."""
    from .env import init_config

    cfg = init_config()
    configure_logging(cfg)
    asyncio.run(_start_scheduler(module))


async def _start_scheduler(module_filter: str | None = None) -> None:
    from .plugins.scheduler.runner import run_scheduler
    from .shared.db import close_client
    from .wiring import build_runtime

    modules = build_runtime()
    await run_scheduler(modules, module_filter=module_filter, on_shutdown=close_client)
