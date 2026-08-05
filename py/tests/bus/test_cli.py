"""`bus --once` — the manual check, which writes nothing.

Worth its own file because CI cannot cover it: the clean-venv job runs
only `--poller bus-hssc`, and the `_run_once` docstring already records
what that gap cost once — the jongro path died with a raw traceback where
the hssc path printed a sentence, and the check could not have seen the
difference.

Nothing here may reach storage. That is the command's whole premise: you
run it against a live upstream to find out whether it still looks like the
captured fixtures, and running it must be safe to repeat.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest
import respx
from click.testing import CliRunner

from skkuverse_crawler.env import init_config
from skkuverse_crawler.modules.bus.cli import _describe, bus_cli

NAVER_HOST = "naveropenapi.apigw.ntruss.com"


@pytest.fixture()
def cli(monkeypatch):
    """A runner over a config built from env vars this test set.

    Two stubs, both load-bearing:

    - `init_config(force=True)`, because `bus_cli` calls `init_config()`
      without it and the conftest's already-cached singleton would win.
    - `configure_logging` is patched out even though no test here cares
      about logs: the real one calls `structlog.reset_defaults()` and
      reconfigures globally, which silently breaks every capture_logs-based
      test that runs after it. Same guard, same reason, as
      tests/notices/test_cli_json.py.
    """

    def run(args, **env):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        init_config(force=True)
        with patch(
            "skkuverse_crawler.modules.bus.cli.configure_logging",
            lambda cfg, *, stream=None: None,
        ):
            return CliRunner().invoke(bus_cli, args)

    return run


def _naver_ok():
    return httpx.Response(
        200,
        json={
            "code": 0,
            "message": "ok",
            "route": {
                "traoptimal": [{"summary": {"duration": 1_800_000, "distance": 45_000}}]
            },
        },
    )


class TestCampusEta:
    @respx.mock
    def test_it_prints_the_document(self, cli):
        respx.route(host=NAVER_HOST).mock(return_value=_naver_ok())
        result = cli(
            ["--once", "--poller", "bus-campus-eta"],
            NAVER_API_KEY_ID="id",
            NAVER_API_KEY="secret",
        )
        assert result.exit_code == 0, result.output
        assert "campus_eta: 1 document" in result.output

    @respx.mock
    def test_json_mode_emits_the_payload(self, cli):
        respx.route(host=NAVER_HOST).mock(return_value=_naver_ok())
        result = cli(
            ["--once", "--poller", "bus-campus-eta", "--json"],
            NAVER_API_KEY_ID="id",
            NAVER_API_KEY="secret",
        )
        assert result.exit_code == 0, result.output
        line = json.loads(result.stdout.strip().splitlines()[-1])
        assert line["key"] == "campus_eta", "the LIVE key — this command writes nothing"
        assert line["payload"]["inja"]["durationText"] == "30분"

    def test_missing_credentials_are_a_sentence_not_a_traceback(self, cli):
        result = cli(
            ["--once", "--poller", "bus-campus-eta"],
            NAVER_API_KEY_ID="",
            NAVER_API_KEY="",
        )
        assert result.exit_code != 0
        assert "NAVER_API_KEY_ID" in result.output
        assert "Traceback" not in result.output

    @respx.mock
    def test_a_bad_naver_response_is_a_sentence_not_a_traceback(self, cli):
        """Strict here, unlike the scheduled module: a manual check that
        half-succeeded and printed a payload anyway is the one outcome this
        command exists to rule out."""
        respx.route(host=NAVER_HOST).mock(
            return_value=httpx.Response(200, json={"code": 3, "message": "출발지 오류"})
        )
        result = cli(
            ["--once", "--poller", "bus-campus-eta"],
            NAVER_API_KEY_ID="id",
            NAVER_API_KEY="secret",
        )
        assert result.exit_code != 0
        assert "code=3" in result.output
        assert "Traceback" not in result.output

    @respx.mock
    def test_an_unreachable_upstream_exits_non_zero(self, cli):
        respx.route(host=NAVER_HOST).mock(return_value=httpx.Response(503))
        result = cli(
            ["--once", "--poller", "bus-campus-eta"],
            NAVER_API_KEY_ID="id",
            NAVER_API_KEY="secret",
        )
        assert result.exit_code == 1
        assert "upstream unavailable" in result.output


class TestHsscRefusal:
    def test_it_names_both_environment_variables(self, cli):
        """The clean-venv CI job greps this exact path for "not configured"
        to prove the module imports without any extra installed."""
        result = cli(
            ["--once", "--poller", "bus-hssc"],
            API_HSSC_NEW_PROD="",
            API_HSSC_NEW_DEV="",
        )
        assert result.exit_code != 0
        assert "not configured" in result.output
        assert "API_HSSC_NEW_PROD" in result.output


class TestDescribe:
    """Payloads are not all lists — campus ETA publishes one object with a
    leg per direction, where `len()` would report "2 item(s)" for a
    document that has none."""

    @pytest.mark.parametrize(
        "payload,expected",
        [
            (None, "no write"),
            ([], "0 item(s)"),
            ([{"a": 1}, {"b": 2}], "2 item(s)"),
            ({"inja": None, "jain": None}, "1 document"),
        ],
    )
    def test_each_shape(self, payload, expected):
        assert _describe(payload) == expected
