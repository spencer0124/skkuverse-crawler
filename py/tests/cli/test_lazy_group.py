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
from unittest.mock import patch
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from skkuverse_crawler.cli import _LAZY, _LazyGroup, main


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
    """`set(_LAZY) <= set(listed)` and sortedness are true by construction,
    so neither is asserted here. What can actually break is the super()
    half — an override that forgets it drops every inline command."""
    ctx = click.Context(main)
    listed = main.list_commands(ctx)
    assert "start" in listed, "inline @main.command()s must still be listed"
    assert set(listed) == set(_LAZY) | set(main.commands)


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
    # NB: not asserting "motor" appears — this test's own fake ImportError
    # message contains it, so that would be circular. The live detection
    # path (find_spec) is covered by test_missing_extra_detected_by_probe.


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


def test_missing_extra_detected_by_probe_not_by_import_failure(monkeypatch):
    """The live path. The CLI leaves import fine without their driver — that
    is what makes --help cheap — so ImportError never fires in a real
    core-only install and the hint has to come from find_spec."""
    import importlib.util

    real = importlib.util.find_spec

    def _no_motor(name, package=None):
        return None if name == "motor" else real(name, package)

    monkeypatch.setattr("skkuverse_crawler.cli.importlib.util.find_spec", _no_motor)

    result = CliRunner().invoke(main, ["update-check"])
    assert result.exit_code != 0
    assert "skkuverse-crawler[mongo]" in result.output


def test_completion_does_not_raise_when_an_extra_is_missing(monkeypatch):
    """Click calls get_command for every name while completing, and treats
    it as a lookup that returns None. Raising there puts a traceback in the
    user's terminal on every TAB press."""
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(
        "skkuverse_crawler.cli.importlib.util.find_spec",
        lambda name, package=None: None if name in {"motor", "tenacity"} else real(name, package),
    )

    ctx = click.Context(main, resilient_parsing=True)
    for name in _LAZY:
        # Must not raise; None (module genuinely absent) is an acceptable answer.
        main.get_command(ctx, name)


def test_a_duplicate_registration_does_not_break_help():
    """A name in both _LAZY and self.commands must render once, not crash.
    Sorting (name, Command) tuples raises TypeError on a tie because
    click.Command has no ordering."""
    from skkuverse_crawler.modules.notices.cli import notices_cli

    group = _LazyGroup("main", help=main.help)
    group.add_command(notices_cli)

    result = CliRunner().invoke(group, ["--help"])
    assert result.exit_code == 0, result.output
    assert result.output.count("\n  notices ") == 1, "duplicate row rendered"


def test_hidden_commands_are_not_listed_in_help():
    """Stock click omits hidden commands; an override that forgets to would
    expose a debug command in the public help."""
    group = _LazyGroup("main", help=main.help)

    @group.command(hidden=True)
    def secret():
        """Should not appear."""

    result = CliRunner().invoke(group, ["--help"])
    assert result.exit_code == 0
    assert "secret" not in result.output


class TestStartModuleSelection:
    """`--module` parsing, which had no CLI-level coverage at all.

    The wiring tests exercise the selection; nothing exercised the split
    that feeds it, which is where an empty string could turn "run these"
    into "run everything".
    """

    @staticmethod
    def _selection_for(arg):
        seen = {}

        async def fake_start(selection=None):
            seen["selection"] = selection

        # configure_logging must be patched too: letting it run reconfigures
        # structlog process-wide, which silently stops structlog.testing's
        # capture_logs from capturing anything in every test that follows.
        with patch("skkuverse_crawler.cli._start_scheduler", fake_start), patch(
            "skkuverse_crawler.cli.init_config", create=True
        ), patch("skkuverse_crawler.cli.configure_logging", create=True):
            args = ["start"] + ([] if arg is None else ["--module", arg])
            result = CliRunner().invoke(main, args)
        assert result.exit_code == 0, result.output
        return seen["selection"]

    def test_no_option_means_every_module(self):
        assert self._selection_for(None) is None

    def test_a_comma_list_becomes_a_list(self):
        assert self._selection_for("notices,notices-summary") == [
            "notices",
            "notices-summary",
        ]

    def test_an_empty_string_does_not_silently_mean_everything(self):
        """`--module ""` under truthiness would become None — "run all" —
        the exact opposite of what was asked. The split-container
        deployment passes this through compose as `--module ${VAR}`, where
        an unset variable interpolates to an empty argument; the failure
        mode would be a second full crawler nobody ordered."""
        assert self._selection_for("") == [""]
