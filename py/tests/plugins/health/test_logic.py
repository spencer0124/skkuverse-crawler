from __future__ import annotations

from datetime import datetime, timezone

from skkuverse_crawler.plugins.health.logic import (
    THRESHOLD,
    decide_transitions,
    format_alert_message,
    format_daily_summary,
)
from skkuverse_crawler.core.results import SourceResult as DeptResult

NOW = datetime(2026, 7, 29, 3, 0, tzinfo=timezone.utc)


def _down(dept_id: str = "sls-special", error: str = "404 Not Found") -> DeptResult:
    return DeptResult(
        dept_id=dept_id, dept_name="법학전문대학원",
        errors=1, source_down=True, last_error=error,
    )


def _ok(dept_id: str = "sls-special", inserted: int = 0) -> DeptResult:
    return DeptResult(dept_id=dept_id, dept_name="법학전문대학원", inserted=inserted)


class TestDecideTransitions:
    def test_first_failure_no_alert(self):
        tr = decide_transitions({}, [_down()], NOW)
        assert tr.alerts == []
        assert tr.new_states["sls-special"]["consecutiveFailures"] == 1
        assert tr.new_states["sls-special"]["alerted"] is False

    def test_threshold_crossing_fires_once(self):
        prev = {"sls-special": {"consecutiveFailures": THRESHOLD - 1, "alerted": False}}
        tr = decide_transitions(prev, [_down()], NOW)
        assert [e.source_id for e in tr.alerts] == ["sls-special"]
        assert tr.new_states["sls-special"]["alerted"] is True

    def test_already_alerted_does_not_refire(self):
        prev = {"sls-special": {"consecutiveFailures": 10, "alerted": True}}
        tr = decide_transitions(prev, [_down()], NOW)
        assert tr.alerts == []
        assert tr.new_states["sls-special"]["consecutiveFailures"] == 11

    def test_skipped_tick_still_fires_past_threshold(self):
        """`>= and not alerted` — 재배포로 크로싱 틱을 놓쳐도 발화."""
        prev = {"sls-special": {"consecutiveFailures": THRESHOLD + 2, "alerted": False}}
        tr = decide_transitions(prev, [_down()], NOW)
        assert len(tr.alerts) == 1

    def test_recovery_only_when_alerted(self):
        prev = {"sls-special": {"consecutiveFailures": 2, "alerted": False}}
        tr = decide_transitions(prev, [_ok()], NOW)
        assert tr.recoveries == []
        assert tr.new_states["sls-special"]["consecutiveFailures"] == 0

    def test_recovery_after_alert(self):
        prev = {"sls-special": {"consecutiveFailures": 5, "alerted": True}}
        tr = decide_transitions(prev, [_ok(inserted=4)], NOW)
        assert [e.source_id for e in tr.recoveries] == ["sls-special"]
        assert tr.recoveries[0].inserted == 4
        assert tr.new_states["sls-special"]["alerted"] is False

    def test_refailure_after_recovery_crosses_again(self):
        prev = {"sls-special": {"consecutiveFailures": 0, "alerted": False}}
        for _ in range(THRESHOLD):
            tr = decide_transitions(prev, [_down()], NOW)
            prev = tr.new_states
        assert len(tr.alerts) == 1

    def test_partial_errors_not_source_down(self):
        """상세 페이지 부분 실패(errors>0, source_down=False)는 정상 취급."""
        r = DeptResult(dept_id="sco", dept_name="글로벌융합학부(공통)", errors=2)
        prev = {"sco": {"consecutiveFailures": 2, "alerted": False}}
        tr = decide_transitions(prev, [r], NOW)
        assert tr.new_states["sco"]["consecutiveFailures"] == 0

    def test_success_preserves_last_failure_info(self):
        prev = {"sls-special": {
            "consecutiveFailures": 5, "alerted": True,
            "lastFailureAt": NOW, "lastError": "404",
        }}
        tr = decide_transitions(prev, [_ok()], NOW)
        state = tr.new_states["sls-special"]
        assert state["lastError"] == "404"
        assert state["lastFailureAt"] == NOW


class TestFormatting:
    def test_no_message_when_quiet(self):
        tr = decide_transitions({}, [_ok()], NOW)
        assert format_alert_message(tr) is None

    def test_alert_message_contains_source_and_error(self):
        prev = {"sls-special": {"consecutiveFailures": THRESHOLD - 1, "alerted": False}}
        tr = decide_transitions(prev, [_down(error="Client error '404 Not Found' for url")], NOW)
        msg = format_alert_message(tr)
        assert msg is not None
        assert "sls-special" in msg and "404" in msg and "크롤 소스 중단" in msg

    def test_batched_alerts_single_message(self):
        prev = {
            "a": {"consecutiveFailures": THRESHOLD - 1, "alerted": False},
            "b": {"consecutiveFailures": THRESHOLD - 1, "alerted": False},
        }
        results = [_down("a"), _down("b")]
        msg = format_alert_message(decide_transitions(prev, results, NOW))
        assert msg is not None and msg.count("•") == 2

    def test_daily_summary_format(self):
        failing = [{
            "sourceId": "cheme", "sourceName": "화학공학과",
            "consecutiveFailures": 52, "lastSuccessAt": None,
        }]
        msg = format_daily_summary(
            now=NOW, enabled_count=148, failing=failing, inserted_24h=74,
        )
        assert "148개 활성" in msg and "정상 147" in msg
        assert "cheme" in msg and "52틱" in msg and "74건" in msg
