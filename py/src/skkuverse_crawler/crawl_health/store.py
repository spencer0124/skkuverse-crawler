"""Thin async orchestration around crawl_health state + Discord alerts.

``record_and_alert`` is hooked at the end of ``NoticesModule.run`` (scheduler
path only — ``--once`` CLI runs stay side-effect-free for health state).
It must never raise: health bookkeeping failing cannot be allowed to mark a
successful crawl cycle as failed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import UpdateOne

from ..notices.orchestrator import DeptResult
from ..shared.db import get_db
from ..shared.discord import send_discord
from ..shared.logger import get_logger
from .logic import decide_transitions, format_alert_message

logger = get_logger("crawl_health")

COLLECTION = "crawl_health"


async def load_states() -> dict[str, dict[str, Any]]:
    db = await get_db()
    return {doc["sourceId"]: doc async for doc in db[COLLECTION].find({})}


async def record_and_alert(results: list[DeptResult]) -> None:
    try:
        prev = await load_states()
        tr = decide_transitions(prev, results, now=datetime.now(timezone.utc))

        if tr.new_states:
            db = await get_db()
            await db[COLLECTION].bulk_write(
                [
                    UpdateOne({"sourceId": sid}, {"$set": state}, upsert=True)
                    for sid, state in tr.new_states.items()
                ],
                ordered=False,
            )

        message = format_alert_message(tr)
        if message:
            logger.info(
                "crawl_health_transition",
                alerts=[e.source_id for e in tr.alerts],
                recoveries=[e.source_id for e in tr.recoveries],
            )
            await send_discord(message)
    except Exception as exc:  # noqa: BLE001 — health must not break the crawl
        logger.warning("crawl_health_record_failed", err=type(exc).__name__, err_msg=str(exc)[:200])
