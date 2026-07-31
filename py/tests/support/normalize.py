"""BSON normalization shared by the conformance and characterization suites.

Two consumers, two datetime modes:

- conformance (``datetime_to="iso"``): scenarios use FIXED datetimes, so both
  backends must produce the *same* value — comparing real ISO strings also
  verifies the fake's millisecond truncation against real BSON.
- goldens (``datetime_to="placeholder"``): the crawl stamps ``now()``, so the
  value differs per run and only its presence/position is pinned.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId


def normalize_bson(value: Any, *, datetime_to: str = "iso", drop_id: bool = True) -> Any:
    if isinstance(value, dict):
        return {
            k: normalize_bson(v, datetime_to=datetime_to, drop_id=drop_id)
            for k, v in value.items()
            if not (drop_id and k == "_id")
        }
    if isinstance(value, (list, tuple)):
        # Tuples (e.g. FakeCollection.ops entries, create_index key pairs)
        # become lists — JSON has no tuple, and the snapshot is JSON anyway.
        return [normalize_bson(v, datetime_to=datetime_to, drop_id=drop_id) for v in value]
    if isinstance(value, datetime):
        if datetime_to == "placeholder":
            return "<UTC_DATETIME>"
        # Real Mongo returns naive UTC datetimes; the fake stores tz-aware.
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    if isinstance(value, ObjectId):
        return "<OID>"
    return value


def sort_docs(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic order for comparing collection dumps (natural order is not
    guaranteed by real Mongo)."""
    return sorted(docs, key=lambda d: json.dumps(d, sort_keys=True, ensure_ascii=False, default=str))
