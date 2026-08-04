"""Trigger selection — the one part of scheduling that had no coverage.

run_scheduler itself blocks on a signal, so it is not unit-testable
without a fake event loop; what is worth pinning is the rule that decides
whether and how a module gets scheduled, since a module silently not
being scheduled is exactly the failure nobody notices.
"""

from __future__ import annotations

from structlog.testing import capture_logs

from skkuverse_crawler.core.module import ModuleConfig
from skkuverse_crawler.plugins.scheduler.runner import (
    DEFAULT_MISFIRE_GRACE_SECONDS,
    _log_missed_ticks,
    build_trigger,
    grace_seconds,
)


class _Module:
    def __init__(self, config: ModuleConfig) -> None:
        self._config = config

    @property
    def config(self) -> ModuleConfig:
        return self._config

    async def run(self, **kwargs):
        return {}

    async def shutdown(self) -> None:
        return None


def test_cron_schedule_builds_a_cron_trigger():
    from apscheduler.triggers.cron import CronTrigger

    trigger = build_trigger(_Module(ModuleConfig(name="m", cron_schedule="*/30 * * * *")))
    assert isinstance(trigger, CronTrigger)


def test_interval_builds_an_interval_trigger():
    from apscheduler.triggers.interval import IntervalTrigger

    trigger = build_trigger(_Module(ModuleConfig(name="m", interval_seconds=60)))
    assert isinstance(trigger, IntervalTrigger)


def test_cron_wins_when_both_are_set():
    from apscheduler.triggers.cron import CronTrigger

    trigger = build_trigger(
        _Module(ModuleConfig(name="m", cron_schedule="0 9 * * *", interval_seconds=60))
    )
    assert isinstance(trigger, CronTrigger)


def test_module_with_neither_is_not_scheduled():
    assert build_trigger(_Module(ModuleConfig(name="m"))) is None


def test_every_wired_module_gets_a_trigger():
    """A registered module that silently never fires is the failure mode
    this guards: every module wiring assembles must be schedulable."""
    from unittest.mock import patch

    from skkuverse_crawler import wiring

    with patch("skkuverse_crawler.core.registry.register"):
        modules = wiring.build_runtime()

    unscheduled = [m.config.name for m in modules if build_trigger(m) is None]
    assert not unscheduled, f"modules that would never run: {unscheduled}"


class TestMisfireGrace:
    """A dropped tick is silent, so the number that decides it is worth pinning.

    Misfire is evaluated before coalesce: a tick later than the grace window
    is skipped entirely, not merged into the next run. The tolerance that
    suits a 30-minute cron would swallow most of a 10-second poller's ticks,
    which is why it is per-module rather than one constant for every job.
    """

    def test_unset_falls_back_to_the_plugin_default(self):
        assert grace_seconds(ModuleConfig(name="m")) == DEFAULT_MISFIRE_GRACE_SECONDS

    def test_the_default_is_the_value_every_job_used_to_be_given(self):
        """Pins the fallback against the hardcoded literal it replaced, so
        making it configurable did not quietly retune the existing modules."""
        assert DEFAULT_MISFIRE_GRACE_SECONDS == 10

    def test_a_module_can_tighten_or_widen_it(self):
        assert grace_seconds(ModuleConfig(name="fast", misfire_grace_time=2)) == 2
        assert grace_seconds(ModuleConfig(name="slow", misfire_grace_time=600)) == 600

    def test_zero_is_honoured_rather_than_treated_as_unset(self):
        """`if not config.misfire_grace_time` would turn 0 into the default.
        Zero means "run only if exactly on time" and is a real choice."""
        assert grace_seconds(ModuleConfig(name="strict", misfire_grace_time=0)) == 0


class TestMissedTickListener:
    def test_it_registers_for_the_missed_event(self):
        from apscheduler.events import EVENT_JOB_MISSED

        registered: list[int] = []

        class _FakeScheduler:
            def add_listener(self, fn, mask):
                registered.append(mask)

        _log_missed_ticks(_FakeScheduler())
        assert registered == [EVENT_JOB_MISSED]

    def test_the_log_names_the_module_that_lost_the_tick(self):
        from apscheduler.events import EVENT_JOB_MISSED

        captured = {}

        class _FakeScheduler:
            def add_listener(self, fn, mask):
                captured["fn"] = fn

        _log_missed_ticks(_FakeScheduler())

        class _Event:
            job_id = "bus-hssc"
            scheduled_run_time = "2026-08-04T09:00:00+09:00"

        with capture_logs() as logs:
            captured["fn"](_Event())
        assert logs[0]["event"] == "job_tick_missed"
        # The job id IS the module name — that is why run_scheduler sets it.
        assert logs[0]["module"] == "bus-hssc"
        assert EVENT_JOB_MISSED  # the mask exists in this apscheduler version
