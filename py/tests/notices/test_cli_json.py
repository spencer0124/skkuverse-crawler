"""`notices --json` — the core-only entry point.

It had no test at all: the plan's own acceptance gate exercised it by
hand, and the one thing that made it usable (logs to stderr, data to
stdout) was found only by running it for real. These pin the parts that a
StringIO-based sink test structurally cannot see.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import click
import pytest
from click.testing import CliRunner

from skkuverse_crawler.core.crawl import FullSweep
from skkuverse_crawler.core.sinks import JsonLinesSink
from skkuverse_crawler.modules.notices.cli import (
    STORE_LESS_DEFAULT_PAGES,
    _require_store,
    notices_cli,
)


def _invoke(args, run_crawl, configure=None):
    """Invoke the command with its side effects stubbed.

    configure_logging is ALWAYS patched, even when a test does not care
    about it: the real one calls structlog.reset_defaults() and
    reconfigures globally, which silently breaks every capture_logs-based
    test that runs afterwards.
    """
    with (
        patch("skkuverse_crawler.modules.notices.cli.run_crawl", run_crawl),
        patch(
            "skkuverse_crawler.modules.notices.cli.load_and_validate",
            return_value=[{"id": "d", "name": "D"}],
        ),
        patch(
            "skkuverse_crawler.modules.notices.cli.configure_logging",
            configure or (lambda cfg, *, stream=None: None),
        ),
    ):
        return CliRunner().invoke(notices_cli, args)


def test_json_run_is_store_less_and_full_sweep():
    run_crawl = AsyncMock(return_value=[])
    result = _invoke(["--json", "--source", "d", "--pages", "1"], run_crawl)

    assert result.exit_code == 0, result.output
    kwargs = run_crawl.await_args.kwargs
    assert isinstance(kwargs["mode"], FullSweep)
    assert isinstance(kwargs["ports"].sink, JsonLinesSink)


def test_json_without_pages_does_not_sweep_every_source_to_exhaustion():
    """The orchestrator's FullSweep default is 2500 pages. Across ~140
    university servers, a bare `notices --json` at that depth is a
    multi-hour hammering — not what a first-run command should do."""
    run_crawl = AsyncMock(return_value=[])
    result = _invoke(["--json"], run_crawl)

    assert result.exit_code == 0, result.output
    options = run_crawl.await_args.args[1]
    assert options.max_pages == STORE_LESS_DEFAULT_PAGES
    assert options.max_pages is not None and options.max_pages <= 5


def test_explicit_pages_still_wins():
    run_crawl = AsyncMock(return_value=[])
    _invoke(["--json", "--pages", "7"], run_crawl)
    assert run_crawl.await_args.args[1].max_pages == 7


def test_json_path_never_touches_wiring_or_the_db():
    """No store means no motor: the whole point of the core-only path."""
    run_crawl = AsyncMock(return_value=[])

    def _boom(*a, **k):
        raise AssertionError("the --json path must not build Mongo ports")

    with patch("skkuverse_crawler.wiring.notices_ports", _boom):
        result = _invoke(["--json", "--pages", "1"], run_crawl)

    assert result.exit_code == 0, result.output


def test_storing_path_without_motor_suggests_the_extra_or_json():
    # _require_store imports importlib inside the function body, so there is
    # no module-level attribute to patch — target the real one.
    with patch("importlib.util.find_spec", return_value=None):
        with pytest.raises(click.ClickException) as exc:
            _require_store()

    message = str(exc.value)
    assert "skkuverse-crawler[mongo]" in message
    assert "--json" in message, "the message should name the store-less alternative"


def test_json_sends_logs_to_stderr_so_stdout_stays_parseable():
    """The bug a StringIO sink test cannot see: structlog writes to stdout,
    so without this the two streams interleave and the output is not JSON."""
    captured = {}

    def _configure(cfg, *, stream=None):
        captured["stream"] = stream

    _invoke(["--json", "--pages", "1"], AsyncMock(return_value=[]), configure=_configure)
    assert captured["stream"] is not None, "--json must redirect logs off stdout"

    _invoke(["--pages", "1"], AsyncMock(return_value=[]), configure=_configure)
    assert captured["stream"] is None, "the normal path keeps logging to stdout"
