"""The lazy subcommand group — and the three ways it could silently rot.

The group trades a duplicated help string for an import-free `--help`.
That trade is only safe if the duplication is checked, so these tests do
the checking: rendering must match an eager group exactly, every table
entry must resolve to the command it claims, and a missing extra must
produce an install hint rather than a raw ModuleNotFoundError.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from skkuverse_crawler.cli import _LAZY, main


def _eager_equivalent() -> click.Group:
    """The group we would have written without laziness."""
    group = click.Group("main", help=main.help)
    for name, (module, attr, _help, _extras) in _LAZY.items():
        group.add_command(getattr(importlib.import_module(module, "skkuverse_crawler"), attr))
    for name, command in main.commands.items():
        group.add_command(command, name)
    return group


def test_help_is_byte_identical_to_an_eager_group():
    """The whole point: `--help` must not be observably lazy."""
    runner = CliRunner()
    lazy = runner.invoke(main, ["--help"])
    eager = runner.invoke(_eager_equivalent(), ["--help"])

    assert lazy.exit_code == 0
    assert eager.exit_code == 0
    assert lazy.output == eager.output


def test_every_table_entry_resolves_and_still_matches():
    """The duplicated help text is the failure mode — a command whose
    docstring changes leaves the table describing something else."""
    for name, (module, attr, help_text, _extras) in _LAZY.items():
        loaded = importlib.import_module(module, "skkuverse_crawler")
        command = getattr(loaded, attr)
        assert isinstance(command, click.Command)
        assert command.name == name, f"{attr} is registered as {command.name!r}, not {name!r}"
        assert command.help is not None
        assert command.help.strip() == help_text, (
            f"{name}: table says {help_text!r}, command docstring says {command.help.strip()!r}"
        )


def test_list_commands_covers_the_table_and_the_inline_commands():
    ctx = click.Context(main)
    listed = main.list_commands(ctx)
    assert set(_LAZY) <= set(listed)
    assert "start" in listed, "inline @main.command()s must still be listed"
    assert listed == sorted(listed)


def test_get_command_returns_the_real_command():
    ctx = click.Context(main)
    command = main.get_command(ctx, "notices")
    assert command is not None and command.name == "notices"
    assert main.get_command(ctx, "no-such-command") is None


def test_missing_extra_gives_an_install_hint(monkeypatch):
    """A core-only install must say what to install, not raise from four
    frames down inside a plugin."""
    real_import = importlib.import_module

    def _fail_for_mongo(name, package=None):
        if "mongo" in name:
            raise ImportError("No module named 'motor'")
        return real_import(name, package)

    monkeypatch.setattr("skkuverse_crawler.cli.importlib.import_module", _fail_for_mongo)

    result = CliRunner().invoke(main, ["update-check"])
    assert result.exit_code != 0
    assert "skkuverse-crawler[mongo]" in result.output
    assert "motor" in result.output


def test_a_command_with_no_extras_reraises_the_original_error(monkeypatch):
    """`notices` needs no extra, so an ImportError from it is a real bug.
    Dressing it up as an install suggestion would send the reader to fix
    their environment instead of the code."""
    real_import = importlib.import_module

    def _fail_for_notices(name, package=None):
        if "notices" in name:
            raise ImportError("something is genuinely broken")
        return real_import(name, package)

    monkeypatch.setattr("skkuverse_crawler.cli.importlib.import_module", _fail_for_notices)

    with pytest.raises(ImportError, match="genuinely broken"):
        main.get_command(click.Context(main), "notices")


def test_help_leaves_every_subcommand_module_unimported():
    """The claim `--help` makes, checked directly in a fresh interpreter:
    not merely that no heavy third-party package loads, but that none of
    the subcommand modules is imported at all."""
    modules = sorted(meta[0].lstrip(".") for meta in _LAZY.values())
    code = (
        "import sys\n"
        "from click.testing import CliRunner\n"
        "from skkuverse_crawler.cli import main\n"
        "CliRunner().invoke(main, ['--help'])\n"
        f"targets = {modules!r}\n"
        "loaded = [m for m in targets if f'skkuverse_crawler.{m}' in sys.modules]\n"
        "print(','.join(loaded))\n"
        "sys.exit(1 if loaded else 0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"--help imported subcommand modules: {result.stdout.strip()}"
