"""Verify DeptId enum stays in sync with departments.json."""

from __future__ import annotations

import json
from pathlib import Path

from skkuverse_crawler.notices.config.dept_ids import DeptId

# departments.json lives at the repo root (SSOT).
# test file is at py/tests/notices/test_dept_ids.py
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEPARTMENTS_JSON = _REPO_ROOT / "departments.json"


def _load_json_ids() -> set[str]:
    with open(DEPARTMENTS_JSON, encoding="utf-8") as f:
        return {d["id"] for d in json.load(f)}


def test_all_departments_have_enum():
    """Every ID in departments.json must exist as a DeptId enum value."""
    json_ids = _load_json_ids()
    enum_values = {e.value for e in DeptId}
    missing = json_ids - enum_values
    assert not missing, f"departments.json IDs missing from DeptId: {missing}"


def test_no_extra_enums():
    """DeptId must not contain values absent from departments.json."""
    json_ids = _load_json_ids()
    enum_values = {e.value for e in DeptId}
    extra = enum_values - json_ids
    assert not extra, f"DeptId has values not in departments.json: {extra}"


def test_enum_values_match_ids():
    """Enum count must equal departments.json count (1:1 mapping)."""
    json_ids = _load_json_ids()
    assert len(DeptId) == len(json_ids)
