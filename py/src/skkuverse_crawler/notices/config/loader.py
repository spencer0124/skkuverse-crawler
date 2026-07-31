from __future__ import annotations

import json
import os
from importlib import resources
from pathlib import Path
from typing import Any

from ...core.sources import SourceConfigError
from ...shared.logger import get_logger

logger = get_logger("config_loader")

REQUIRED_SELECTORS: dict[str, list[str]] = {
    "skku-standard": ["listItem", "category", "titleLink", "infoList", "detailContent", "attachmentList"],
    "wordpress-api": [],
    "skkumed-asp": ["listItem", "titleLink", "infoList", "detailContent", "attachmentList"],
    "jsp-dorm": ["listRow", "pinnedRow", "titleLink", "detailContent", "attachmentLink"],
    "custom-php": ["listRow", "titleLink", "category", "views", "date", "detailContent"],
    "gnuboard": ["listRow", "titleLink", "author", "date", "detailContent", "detailAttachment"],
    "gnuboard-custom": ["listRow", "titleLink", "date", "meta", "detailContent", "detailAttachment"],
    "pyxis-api": [],
    "webflow-skku": ["listItem", "listLink", "listRow", "titleCell", "regularCell", "paginationNext", "detailTitle", "detailContent"],
}


def _resolve_sources_path(anchor: Path | None = None) -> Path:
    """Resolve sources.json lazily, in precedence order:

    1. SOURCES_JSON_PATH env var (production compose sets /sources.json).
    2. Upward search from this file, skipping package directories (those
       holding an __init__.py) — the bundled copy must never shadow the
       repo-root SSOT in a checkout. This also finds /sources.json in a
       bare container (runtime stage copies it to /).
    3. The bundled package copy (installed wheel with no repo around),
       kept in sync with the repo root by scripts/generate_artifacts.py.

    Resolution is deliberately NOT module-level: import stays IO/env-free
    (structure tests import the whole package with env={}), and tests can
    monkeypatch SOURCES_JSON_PATH.
    """
    env_path = os.environ.get("SOURCES_JSON_PATH")
    if env_path:
        return Path(env_path)

    start = (anchor or Path(__file__)).resolve()
    for parent in start.parents:
        if (parent / "__init__.py").is_file():
            continue  # still inside the package — bundled copy is not the SSOT
        candidate = parent / "sources.json"
        if candidate.is_file():
            return candidate

    # importlib.resources: for a regular (non-zipped) install this is a real
    # filesystem path; we never ship zipped wheels.
    bundled = Path(str(resources.files("skkuverse_crawler.notices.config") / "sources.json"))
    if bundled.is_file():
        return bundled
    raise SourceConfigError(
        "sources.json not found — set SOURCES_JSON_PATH, run from a repo "
        "checkout, or install a wheel with the bundled copy"
    )


def load_and_validate() -> list[dict[str, Any]]:
    path = _resolve_sources_path()
    try:
        configs: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SourceConfigError(f"cannot read sources.json at {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SourceConfigError(f"invalid JSON in sources.json at {path}: {exc}") from exc

    errors: list[str] = []

    for dept in configs:
        strategy = dept.get("strategy", "")
        dept_id = dept.get("id", "unknown")
        required = REQUIRED_SELECTORS.get(strategy)

        if required is None:
            errors.append(f'{dept_id}: unknown strategy "{strategy}"')
            continue

        if not required:
            continue

        selectors = dept.get("selectors")
        if not selectors:
            errors.append(f"{dept_id}: missing selectors object")
            continue

        for sel in required:
            if sel not in selectors:
                errors.append(f'{dept_id}: missing selector "{sel}" for strategy "{strategy}"')

    # Duplicate ID check
    ids: list[str] = []
    for c in configs:
        if "id" not in c:
            errors.append("entry missing required key 'id'")
            continue
        ids.append(c["id"])
    seen: set[str] = set()
    dupes: list[str] = []
    for dept_id in ids:
        if dept_id in seen:
            dupes.append(dept_id)
        seen.add(dept_id)

    if dupes:
        errors.append(f"Duplicate department IDs: {', '.join(dupes)}")

    if errors:
        for err in errors:
            logger.error("config_validation_error", detail=err)
        logger.error("config_validation_failed", count=len(errors))
        raise SourceConfigError(f"sources.json validation failed with {len(errors)} error(s)")

    logger.info("sources_loaded", count=len(configs), path=str(path))
    return configs
