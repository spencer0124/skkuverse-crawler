from __future__ import annotations

import asyncio
import importlib
import importlib.util

import click

from .shared.logger import configure_logging

# extra name -> a distribution that extra installs, used only to detect
# absence. Names differ (`mongo` installs `motor`), so the mapping is
# explicit; test_packaging.py checks it against pyproject.
_EXTRA_MARKER = {
    "mongo": "motor",
    "sched": "apscheduler",
    "discord": "tenacity",
    "ai": "tenacity",
}

# name -> (module, attribute, help text, extras needed to import it)
#
# The help text is duplicated from each command's docstring so that
# `--help` can be rendered without importing anything. Duplication is
# guarded, not trusted: tests/cli/test_lazy_group.py imports every entry
# and asserts the text still matches.
_LAZY: dict[str, tuple[str, str, str, str | None]] = {
    # Extras must list everything the command's import chain needs, not just
    # the one it is named after: health reads crawl_health state out of Mongo
    # (bson + shared.db) and summarize writes summaries back to it.
    "health-summary": (
        ".plugins.health.cli", "health_summary_cli",
        "Send the daily crawl-health summary to Discord once.", "mongo,discord",
    ),
    "notices": (
        ".modules.notices.cli", "notices_cli",
        "Run the notices crawler.", None,
    ),
    "repair-attachments": (
        ".plugins.mongo.cli", "repair_attachments_cli",
        "Repair attachment links stored without a referer or with a stale id.", "mongo",
    ),
    "repair-dimensions": (
        ".plugins.mongo.cli", "repair_dimensions_cli",
        "Repair notices Tier-2 wrote before it ran the content pipeline.", "mongo",
    ),
    "summarize": (
        ".plugins.ai_summary.cli", "summarize_cli",
        "Run AI summarization on unsummarized notices.", "mongo,ai",
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


def _missing_extras_message(cmd_name: str, extras: str, detail: str) -> str:
    return (
        f"`{cmd_name}` needs the optional `{extras}` dependencies — install with:\n"
        f"    pip install 'skkuverse-crawler[{extras}]'\n"
        f"({detail})"
    )


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
        # Shell completion calls get_command for every name and click treats
        # it as a lookup that returns None, not one that raises — a missing
        # extra there must not put a traceback in the user's terminal.
        if extras is not None and not ctx.resilient_parsing:
            self._require_extras(cmd_name, extras)
        try:
            loaded = importlib.import_module(module, __package__)
        except ImportError as exc:
            if extras is None or ctx.resilient_parsing:
                raise
            raise click.ClickException(_missing_extras_message(cmd_name, extras, str(exc))) from exc
        return getattr(loaded, attr)

    @staticmethod
    def _require_extras(cmd_name: str, extras: str) -> None:
        """Fail with an install hint before the command can fail worse.

        Checked with find_spec rather than by catching ImportError: the CLI
        leaf modules import fine without their driver (that is what makes
        `--help` cheap), so the failure would otherwise surface much later
        as a missing MONGO_URL or a ModuleNotFoundError from deep inside a
        plugin. find_spec does not execute the module, so this stays as
        import-light as the rest of the group.
        """
        for extra in extras.split(","):
            marker = _EXTRA_MARKER.get(extra.strip())
            if marker is None:
                continue
            try:
                found = importlib.util.find_spec(marker) is not None
            except ModuleNotFoundError:
                found = False
            if not found:
                raise click.ClickException(
                    _missing_extras_message(cmd_name, extras, f"no module named {marker!r}")
                )

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        # Eagerly-registered commands win over the table: if a name exists in
        # both, the real Command is the truth and the placeholder is stale.
        # Keyed by name rather than sorting tuples, because click.Command has
        # no ordering and `rows.sort()` on ties raises TypeError.
        by_name: dict[str, click.Command] = {
            name: click.Command(name, help=meta[2]) for name, meta in _LAZY.items()
        }
        by_name.update(self.commands)

        # Click's own format_commands hides `hidden` commands; a placeholder
        # can never be hidden, but a real one can.
        rows = [(name, cmd) for name, cmd in sorted(by_name.items()) if not cmd.hidden]
        if not rows:
            return

        limit = formatter.width - 6 - max(len(name) for name, _ in rows)
        with formatter.section("Commands"):
            formatter.write_dl([(name, cmd.get_short_help_str(limit)) for name, cmd in rows])


@click.group(cls=_LazyGroup)
def main() -> None:
    """skkuverse-crawler: Multi-module SKKU data crawler."""
    pass


@main.command()
@click.option(
    "--module",
    "-m",
    default=None,
    help="Comma-separated module names to run (default: all). Unknown names are an error.",
)
def start(module: str | None) -> None:
    """Start the cron scheduler for all (or some) modules."""
    from .env import init_config

    cfg = init_config()
    configure_logging(cfg)
    # Split here, not in wiring: "a comma means several" is a CLI spelling
    # decision, and wiring takes a sequence so a library caller can pass a
    # list without stringifying it first.
    selection = module.split(",") if module else None
    asyncio.run(_start_scheduler(selection))


async def _start_scheduler(selection: list[str] | None = None) -> None:
    from .plugins.scheduler.runner import run_scheduler
    from .shared.db import close_client
    from .wiring import build_runtime

    modules = build_runtime(selection=selection)
    await run_scheduler(modules, on_shutdown=close_client)
