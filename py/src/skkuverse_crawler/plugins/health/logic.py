"""Pure decision logic for crawl-health alerting.

No I/O here — ``store.py`` loads previous states, calls
``decide_transitions``, persists the new states, and sends the message.
This split keeps the alert/recovery semantics unit-testable without a DB
(same architecture as attachment_validator: pure checks + thin orchestrator).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from ...core.results import SourceResult

# Consecutive source-down ticks before a single alert fires (~1.5h at the
# 30-min notices cadence). Fires once per outage: `alerted` latches until
# the source recovers.
THRESHOLD = 3

_KST = timezone(timedelta(hours=9))

_ERROR_SNIPPET_LEN = 120


@dataclass(frozen=True)
class SourceEvent:
    source_id: str
    source_name: str
    consecutive_failures: int = 0
    last_error: str = ""
    last_success_at: datetime | None = None
    inserted: int = 0  # recovery message detail


@dataclass
class HealthTransition:
    alerts: list[SourceEvent] = field(default_factory=list)
    recoveries: list[SourceEvent] = field(default_factory=list)
    # sourceId → full replacement state doc (upserted by store)
    new_states: dict[str, dict[str, Any]] = field(default_factory=dict)


def decide_transitions(
    prev_states: dict[str, dict[str, Any]],
    results: list[SourceResult],
    now: datetime,
    threshold: int = THRESHOLD,
) -> HealthTransition:
    tr = HealthTransition()
    for r in results:
        prev = prev_states.get(r.dept_id, {})
        if r.source_down:
            count = int(prev.get("consecutiveFailures", 0)) + 1
            alerted = bool(prev.get("alerted", False))
            state = {
                "sourceId": r.dept_id,
                "sourceName": r.dept_name,
                "consecutiveFailures": count,
                "lastFailureAt": now,
                "lastError": r.last_error[:500],
                "lastSuccessAt": prev.get("lastSuccessAt"),
                "alerted": alerted,
                "updatedAt": now,
            }
            # `>= and not alerted` (not `==`) so a redeploy that loses a tick
            # or a raised threshold can't permanently suppress the alert.
            if count >= threshold and not alerted:
                state["alerted"] = True
                tr.alerts.append(SourceEvent(
                    source_id=r.dept_id,
                    source_name=r.dept_name,
                    consecutive_failures=count,
                    last_error=r.last_error,
                    last_success_at=prev.get("lastSuccessAt"),
                ))
        else:
            if prev.get("alerted"):
                tr.recoveries.append(SourceEvent(
                    source_id=r.dept_id,
                    source_name=r.dept_name,
                    inserted=r.inserted,
                ))
            state = {
                "sourceId": r.dept_id,
                "sourceName": r.dept_name,
                "consecutiveFailures": 0,
                "lastFailureAt": prev.get("lastFailureAt"),
                "lastError": prev.get("lastError", ""),
                "lastSuccessAt": now,
                "alerted": False,
                "updatedAt": now,
            }
        tr.new_states[r.dept_id] = state
    return tr


def _fmt_kst(dt: datetime | None) -> str:
    if dt is None:
        return "기록 없음"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_KST).strftime("%m-%d %H:%M")


def format_alert_message(tr: HealthTransition) -> str | None:
    """One batched Discord message per tick; None when nothing to say."""
    if not tr.alerts and not tr.recoveries:
        return None
    lines: list[str] = []
    if tr.alerts:
        lines.append(f"🚨 **크롤 소스 중단** (연속 {THRESHOLD}틱 실패)")
        for e in tr.alerts:
            err = e.last_error.splitlines()[0][:_ERROR_SNIPPET_LEN] if e.last_error else "unknown"
            lines.append(
                f"• {e.source_name} (`{e.source_id}`) — {err}"
                f" (마지막 성공: {_fmt_kst(e.last_success_at)})"
            )
    if tr.recoveries:
        lines.append("✅ **회복**")
        for e in tr.recoveries:
            lines.append(f"• {e.source_name} (`{e.source_id}`) — 이번 틱 {e.inserted}건 수집")
    return "\n".join(lines)


def format_daily_summary(
    *,
    now: datetime,
    enabled_count: int,
    failing: list[dict[str, Any]],
    inserted_24h: int,
) -> str:
    lines = [
        f"📊 **크롤러 일일 요약** ({_fmt_kst(now)} KST)",
        f"소스: {enabled_count}개 활성 · 정상 {enabled_count - len(failing)} · 실패 중 {len(failing)}",
        f"최근 24시간 신규 공지: {inserted_24h}건",
    ]
    if failing:
        lines.append("⚠️ 실패 중:")
        for doc in sorted(failing, key=lambda d: -int(d.get("consecutiveFailures", 0))):
            lines.append(
                f"• {doc.get('sourceName', '?')} (`{doc.get('sourceId')}`)"
                f" — {doc.get('consecutiveFailures')}틱 연속"
                f" (마지막 성공: {_fmt_kst(doc.get('lastSuccessAt'))})"
            )
    return "\n".join(lines)
