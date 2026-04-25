"""Verify SourceId enum stays in sync with sources.json."""

from __future__ import annotations

import json
from pathlib import Path

from skkuverse_crawler.notices.config.source_ids import SourceId

# sources.json lives at the repo root (SSOT).
# test file is at py/tests/notices/test_source_ids.py
_REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCES_JSON = _REPO_ROOT / "sources.json"


def _load_json_ids() -> set[str]:
    with open(SOURCES_JSON, encoding="utf-8") as f:
        return {d["id"] for d in json.load(f)}


def test_all_sources_have_enum():
    """Every ID in sources.json must exist as a SourceId enum value."""
    json_ids = _load_json_ids()
    enum_values = {e.value for e in SourceId}
    missing = json_ids - enum_values
    assert not missing, f"sources.json IDs missing from SourceId: {missing}"


def test_no_extra_enums():
    """SourceId must not contain values absent from sources.json."""
    json_ids = _load_json_ids()
    enum_values = {e.value for e in SourceId}
    extra = enum_values - json_ids
    assert not extra, f"SourceId has values not in sources.json: {extra}"


def test_enum_values_match_ids():
    """Enum count must equal sources.json count (1:1 mapping)."""
    json_ids = _load_json_ids()
    assert len(SourceId) == len(json_ids)
