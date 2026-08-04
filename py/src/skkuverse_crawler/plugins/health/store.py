"""Thin async orchestration around crawl-health state + operator alerts.

``record_and_alert`` is the hook wiring installs at the end of
``NoticesModule.run`` (scheduler path only — ``--once`` CLI runs stay
side-effect-free for health state). It must never raise: health
bookkeeping failing cannot be allowed to mark a successful crawl cycle as
failed.

Alerting goes through a ``Notifier``, never through a Discord import.
Wiring decides what satisfies the port; this plugin only knows it can
send a string somewhere. That is what keeps plugins/health →
plugins/discord from becoming a hard edge (architecture ownership table).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import UpdateOne

from ...core.ports import Notifier
from ...core.results import SourceResult
from ...shared.db import get_db
from ...shared.logger import get_logger
from .logic import THRESHOLD, decide_transitions, format_alert_message

logger = get_logger("crawl_health")

COLLECTION = "crawl_health"


async def load_states() -> dict[str, dict[str, Any]]:
    db = await get_db()
    return {doc["sourceId"]: doc async for doc in db[COLLECTION].find({})}


async def record_and_alert(
    results: list[SourceResult],
    *,
    notifier: Notifier,
    threshold: int = THRESHOLD,
    label: str | None = None,
) -> None:
    """Record this tick's health and alert on transitions.

    ``threshold`` is per-caller because ticks are not comparable across
    modules: three consecutive failures is ninety minutes of a half-hourly
    crawl and thirty seconds of a ten-second poller. Leaving one constant
    for both would page on a poller's first flap.

    ``label`` names the origin, for when more than one process alerts to
    the same webhook.
    """
    try:
        prev = await load_states()
        tr = decide_transitions(
            prev, results, now=datetime.now(timezone.utc), threshold=threshold
        )

        if tr.new_states:
            db = await get_db()
            await db[COLLECTION].bulk_write(
                [
                    UpdateOne({"sourceId": sid}, {"$set": state}, upsert=True)
                    for sid, state in tr.new_states.items()
                ],
                ordered=False,
            )

        message = format_alert_message(tr, threshold=threshold, label=label)
        if message:
            logger.info(
                "crawl_health_transition",
                alerts=[e.source_id for e in tr.alerts],
                recoveries=[e.source_id for e in tr.recoveries],
            )
            await notifier.notify(message)
    except Exception as exc:  # noqa: BLE001 — health must not break the crawl
        logger.warning("crawl_health_record_failed", err=type(exc).__name__, err_msg=str(exc)[:200])
