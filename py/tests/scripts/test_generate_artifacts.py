"""Validation tests for scripts/generate_artifacts.py.

Tests are grouped by responsibility area:

* TestRequiredFields    — all expected keys are demanded on each entry
* TestFieldTypes        — wrong types are rejected with clear errors
* TestExcludeReasonEnum — only known reason keys (or null) accepted
* TestSemanticRules     — three contradiction patterns rejected;
                          three valid (avail, enabled, reason) combos pass
* TestCategoryRules     — fixed/picker integrity vs. dept availability
* TestPickerArtifact    — picker emits crawlable + intentionally-unsupported
* TestCronFilterArtifact— docker env line includes only depts that crawl
* TestServerSourcesArtifact — schema carries new fields, drops legacy
* TestRealSourcesSmoke  — current SSOT file passes the full validator
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

# scripts/ is not a regular package, so import via importlib.
_REPO_PY_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_PY_ROOT / "scripts" / "generate_artifacts.py"
_REPO_ROOT = _REPO_PY_ROOT.parent
_SOURCES_JSON = _REPO_ROOT / "sources.json"
_CATEGORIES_JSON = _REPO_ROOT / "categories.json"

_spec = importlib.util.spec_from_file_location("generate_artifacts", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
ga = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ga)


def _make_dept(**overrides) -> dict:
    """A fully-valid dept entry; tests override one or two fields to
    exercise the rule under test."""
    base = {
        "id": "test-dept",
        "name": "Test Dept",
        "strategy": "skku-standard",
        "campus": "nsc",
        "college": "공과대학",
        "appCategory": "dept",
        "crawlAvailable": True,
        "crawlEnabled": True,
        "excludeReason": None,
        "selectors": {
            "listItem": "x",
            "category": "x",
            "titleLink": "x",
            "infoList": "x",
            "detailContent": "x",
            "attachmentList": "x",
        },
    }
    base.update(overrides)
    return base


_VALID_APP_CATS = {"dept", None}


# ──────────────────────────────────────────────────────────────────────
# Required fields — every key must be present
# ──────────────────────────────────────────────────────────────────────
class TestRequiredFields:
    @pytest.mark.parametrize("missing", [
        "id", "name", "strategy", "campus", "college", "appCategory",
        "crawlAvailable", "crawlEnabled", "excludeReason",
    ])
    def test_missing_field_is_rejected(self, missing):
        dept = _make_dept()
        del dept[missing]
        errors = ga.validate_departments([dept], _VALID_APP_CATS)
        assert any(f"missing required field '{missing}'" in e for e in errors)


# ──────────────────────────────────────────────────────────────────────
# Field type checks — bool fields must be bool
# ──────────────────────────────────────────────────────────────────────
class TestFieldTypes:
    def test_crawlAvailable_must_be_bool(self):
        dept = _make_dept(crawlAvailable="yes")
        errors = ga.validate_departments([dept], _VALID_APP_CATS)
        assert any("crawlAvailable must be boolean" in e for e in errors)

    def test_crawlEnabled_must_be_bool(self):
        dept = _make_dept(crawlEnabled=1)
        errors = ga.validate_departments([dept], _VALID_APP_CATS)
        assert any("crawlEnabled must be boolean" in e for e in errors)


# ──────────────────────────────────────────────────────────────────────
# excludeReason enum
# ──────────────────────────────────────────────────────────────────────
class TestExcludeReasonEnum:
    def test_null_is_valid(self):
        dept = _make_dept(excludeReason=None)
        assert not ga.validate_departments([dept], _VALID_APP_CATS)

    @pytest.mark.parametrize("key", [
        "loginRequired", "noWebsite", "externalSystem",
        "accessRestricted", "temporarilyUnavailable",
    ])
    def test_known_keys_valid(self, key):
        dept = _make_dept(
            crawlAvailable=False, crawlEnabled=False, excludeReason=key,
        )
        assert not ga.validate_departments([dept], _VALID_APP_CATS)

    def test_unknown_key_rejected(self):
        dept = _make_dept(
            crawlAvailable=False, crawlEnabled=False, excludeReason="bogus",
        )
        errors = ga.validate_departments([dept], _VALID_APP_CATS)
        assert any("invalid excludeReason 'bogus'" in e for e in errors)


# ──────────────────────────────────────────────────────────────────────
# Semantic consistency — 3 reject patterns + 3 valid combinations
# ──────────────────────────────────────────────────────────────────────
class TestSemanticRules:
    def test_unavailable_without_reason_is_rejected(self):
        dept = _make_dept(
            crawlAvailable=False, crawlEnabled=False, excludeReason=None,
        )
        errors = ga.validate_departments([dept], _VALID_APP_CATS)
        assert any("requires non-null excludeReason" in e for e in errors)

    def test_available_with_reason_is_rejected(self):
        dept = _make_dept(crawlAvailable=True, excludeReason="loginRequired")
        errors = ga.validate_departments([dept], _VALID_APP_CATS)
        assert any("must have null excludeReason" in e for e in errors)

    def test_unavailable_but_enabled_is_rejected(self):
        dept = _make_dept(
            crawlAvailable=False, crawlEnabled=True, excludeReason="loginRequired",
        )
        errors = ga.validate_departments([dept], _VALID_APP_CATS)
        assert any("forbids crawlEnabled=true" in e for e in errors)

    @pytest.mark.parametrize("avail,enabled,reason,label", [
        (True,  True,  None,             "normal-crawling"),
        (True,  False, None,             "operational-pause"),
        (False, False, "loginRequired",  "intentionally-unsupported"),
    ])
    def test_valid_combinations_pass(self, avail, enabled, reason, label):
        dept = _make_dept(
            crawlAvailable=avail, crawlEnabled=enabled, excludeReason=reason,
        )
        errors = ga.validate_departments([dept], _VALID_APP_CATS)
        assert not errors, f"[{label}] unexpected errors: {errors}"


# ──────────────────────────────────────────────────────────────────────
# Categories validation — interaction with dept availability
# ──────────────────────────────────────────────────────────────────────
class TestCategoryRules:
    def test_fixed_with_unavailable_source_is_rejected(self):
        depts = [_make_dept(
            id="med", crawlAvailable=False, crawlEnabled=False,
            excludeReason="loginRequired",
        )]
        cats = [{
            "id": "academic",
            "tabMode": "fixed",
            "label": {"ko": "학사", "en": "Academic"},
            "fixedSourceId": "med",
        }]
        errors = ga.validate_categories(cats, depts)
        # validate_categories runs separately — picker has 0 matching, plus
        # we check that the unsupported message appears for fixed mode.
        # Ignore the unrelated "matches 0" picker error if any.
        assert any("crawlAvailable=false" in e for e in errors)

    def test_picker_default_must_actually_crawl(self):
        # An unsupported dept must NOT be allowed as a defaultId.
        depts = [
            _make_dept(id="alive"),
            _make_dept(
                id="dead", crawlAvailable=False, crawlEnabled=False,
                excludeReason="loginRequired",
            ),
        ]
        cats = [{
            "id": "dept",
            "tabMode": "picker",
            "label": {"ko": "학과", "en": "Department"},
            "maxSelection": 5,
            "defaultIds": ["dead"],
        }]
        errors = ga.validate_categories(cats, depts)
        assert any("defaultId 'dead'" in e for e in errors)


# ──────────────────────────────────────────────────────────────────────
# Picker artifact — gen_server_categories sourceIds list
# ──────────────────────────────────────────────────────────────────────
class TestPickerArtifact:
    @pytest.fixture
    def picker_output(self):
        cats = [{
            "id": "dept",
            "tabMode": "picker",
            "label": {"ko": "학과", "en": "Department"},
            "maxSelection": 5,
        }]
        depts = [
            _make_dept(id="normal"),
            _make_dept(id="paused", crawlEnabled=False),
            _make_dept(
                id="unsupported", crawlAvailable=False, crawlEnabled=False,
                excludeReason="loginRequired",
            ),
        ]
        out = json.loads(ga.gen_server_categories(cats, depts))
        return next(c for c in out if c["id"] == "dept")

    def test_includes_crawlable(self, picker_output):
        assert "normal" in picker_output["sourceIds"]

    def test_includes_paused(self, picker_output):
        assert "paused" in picker_output["sourceIds"]

    def test_includes_unsupported(self, picker_output):
        assert "unsupported" in picker_output["sourceIds"]


# ──────────────────────────────────────────────────────────────────────
# Cron filter artifact — gen_docker_env
# ──────────────────────────────────────────────────────────────────────
class TestCronFilterArtifact:
    @pytest.fixture
    def env_line(self):
        depts = [
            _make_dept(id="cron-on"),
            _make_dept(id="cron-paused", crawlEnabled=False),
            _make_dept(
                id="cron-unsupported", crawlAvailable=False, crawlEnabled=False,
                excludeReason="loginRequired",
            ),
        ]
        return ga.gen_docker_env(depts).strip()

    def test_includes_crawlable(self, env_line):
        assert "cron-on" in env_line

    def test_excludes_paused(self, env_line):
        assert "cron-paused" not in env_line

    def test_excludes_unsupported(self, env_line):
        assert "cron-unsupported" not in env_line


# ──────────────────────────────────────────────────────────────────────
# Server-sources.json artifact — schema migration
# ──────────────────────────────────────────────────────────────────────
class TestServerSourcesArtifact:
    @pytest.fixture
    def entry(self):
        depts = [_make_dept(id="x", college="공과대학")]
        return json.loads(ga.gen_sources_json(depts))[0]

    def test_emits_crawlAvailable(self, entry):
        assert entry["crawlAvailable"] is True

    def test_emits_excludeReason(self, entry):
        assert entry["excludeReason"] is None

    def test_drops_legacy_noticeAvailable(self, entry):
        assert "noticeAvailable" not in entry, (
            "Legacy noticeAvailable should be dropped — server's tabConfig.js "
            "now derives the client-facing field from crawlAvailable."
        )

    def test_preserves_college(self, entry):
        assert entry["college"] == "공과대학"


# ──────────────────────────────────────────────────────────────────────
# Smoke: the real SSOT files should pass the full validator end-to-end
# ──────────────────────────────────────────────────────────────────────
class TestRealSourcesSmoke:
    def test_real_sources_json_passes(self):
        sources = json.loads(_SOURCES_JSON.read_text(encoding="utf-8"))
        categories = json.loads(_CATEGORIES_JSON.read_text(encoding="utf-8"))
        valid_app_cats = {c["id"] for c in categories} | {None}

        errors = ga.validate_departments(sources, valid_app_cats)
        errors += ga.validate_categories(categories, sources)
        assert not errors, "Real SSOT failed validation:\n  " + "\n  ".join(errors)
