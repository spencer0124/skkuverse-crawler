"""Trigger selection — the one part of scheduling that had no coverage.

run_scheduler itself blocks on a signal, so it is not unit-testable
without a fake event loop; what is worth pinning is the rule that decides
whether and how a module gets scheduled, since a module silently not
being scheduled is exactly the failure nobody notices.
"""

from __future__ import annotations

from skkuverse_crawler.core.module import ModuleConfig
from skkuverse_crawler.plugins.scheduler.runner import build_trigger


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
