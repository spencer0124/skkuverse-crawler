"""First real coverage for the sources loader (PR 3).

Before this, the only tests touching the loader were mock patches of
load_and_validate — the validation rules and the exit path had zero
coverage. These tests exercise the rules for real, plus the new lazy path
resolution (env → upward-search-skipping-package-dirs → bundled copy) and
the SSOT↔package-copy sync guarantee.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from skkuverse_crawler.core.sources import SourceConfigError
from skkuverse_crawler.notices.config import loader
from skkuverse_crawler.notices.config.loader import (
    _resolve_sources_path,
    load_and_validate,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_sources(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return path


def _entry(dept_id: str = "a", strategy: str = "wordpress-api", **extra) -> dict:
    """wordpress-api / pyxis-api require no selectors — smallest valid entry."""
    return {"id": dept_id, "strategy": strategy, **extra}


class TestValidation:
    def _load(self, monkeypatch, tmp_path: Path, entries: list[dict]):
        monkeypatch.setenv("SOURCES_JSON_PATH", str(_write_sources(tmp_path, entries)))
        return load_and_validate()

    def test_valid_minimal_config(self, monkeypatch, tmp_path):
        configs = self._load(monkeypatch, tmp_path, [_entry("a"), _entry("b")])
        assert [c["id"] for c in configs] == ["a", "b"]

    def test_unknown_strategy_raises(self, monkeypatch, tmp_path):
        with pytest.raises(SourceConfigError, match="validation failed"):
            self._load(monkeypatch, tmp_path, [_entry(strategy="no-such-strategy")])

    def test_missing_selectors_object_raises(self, monkeypatch, tmp_path):
        with pytest.raises(SourceConfigError):
            self._load(monkeypatch, tmp_path, [_entry(strategy="gnuboard")])

    def test_missing_individual_selector_raises(self, monkeypatch, tmp_path):
        partial = {"listRow": "tr", "titleLink": "a"}  # gnuboard needs 6
        with pytest.raises(SourceConfigError):
            self._load(
                monkeypatch, tmp_path, [_entry(strategy="gnuboard", selectors=partial)]
            )

    def test_duplicate_ids_raise(self, monkeypatch, tmp_path):
        with pytest.raises(SourceConfigError):
            self._load(monkeypatch, tmp_path, [_entry("dup"), _entry("dup")])

    def test_entry_without_id_raises(self, monkeypatch, tmp_path):
        # Was a raw KeyError before PR 3; now folds into SourceConfigError.
        with pytest.raises(SourceConfigError):
            self._load(monkeypatch, tmp_path, [{"strategy": "wordpress-api"}])

    def test_missing_file_raises(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SOURCES_JSON_PATH", str(tmp_path / "nope.json"))
        with pytest.raises(SourceConfigError, match="cannot read"):
            load_and_validate()

    def test_invalid_json_raises(self, monkeypatch, tmp_path):
        bad = tmp_path / "sources.json"
        bad.write_text("{not json", encoding="utf-8")
        monkeypatch.setenv("SOURCES_JSON_PATH", str(bad))
        with pytest.raises(SourceConfigError, match="invalid JSON"):
            load_and_validate()


class TestResolution:
    def test_env_var_wins(self, monkeypatch, tmp_path):
        custom = tmp_path / "custom.json"
        custom.write_text("[]", encoding="utf-8")
        monkeypatch.setenv("SOURCES_JSON_PATH", str(custom))
        assert _resolve_sources_path() == custom

    def test_upward_search_skips_package_dirs(self, monkeypatch, tmp_path):
        """The bundled in-package copy must never shadow the repo-root SSOT."""
        monkeypatch.delenv("SOURCES_JSON_PATH", raising=False)
        pkg = tmp_path / "repo" / "pkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "sources.json").write_text("[]", encoding="utf-8")  # decoy in package
        ssot = tmp_path / "repo" / "sources.json"
        ssot.write_text("[]", encoding="utf-8")
        anchor = pkg / "loader.py"
        anchor.write_text("", encoding="utf-8")
        assert _resolve_sources_path(anchor=anchor) == ssot

    def test_checkout_resolves_repo_root(self, monkeypatch):
        monkeypatch.delenv("SOURCES_JSON_PATH", raising=False)
        assert _resolve_sources_path() == _REPO_ROOT / "sources.json"

    def test_bundled_fallback_without_repo_markers(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SOURCES_JSON_PATH", raising=False)
        anchor = tmp_path / "lone.py"
        anchor.write_text("", encoding="utf-8")
        resolved = _resolve_sources_path(anchor=anchor)
        assert resolved.name == "sources.json"
        assert "skkuverse_crawler" in str(resolved)
        assert resolved.is_file()


class TestPackageCopySync:
    def test_package_copy_matches_repo_root_byte_for_byte(self):
        """Staleness guard for the codegen-maintained bundled copy.

        Red here means sources.json changed without running
        `python scripts/generate_artifacts.py`.
        """
        bundled = Path(loader.__file__).parent / "sources.json"
        assert bundled.read_bytes() == (_REPO_ROOT / "sources.json").read_bytes()


def test_real_sources_load_and_validate(monkeypatch):
    """The committed sources.json passes its own validation (first real run
    of the rules in the test suite) and the count matches the SSOT."""
    monkeypatch.delenv("SOURCES_JSON_PATH", raising=False)
    configs = load_and_validate()
    root = json.loads((_REPO_ROOT / "sources.json").read_text(encoding="utf-8"))
    assert len(configs) == len(root)
    assert len(configs) > 100
