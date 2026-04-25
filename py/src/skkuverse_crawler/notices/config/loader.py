from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from ...shared.logger import get_logger

# sources.json lives at the repo root (SSOT).
# Docker: set SOURCES_JSON_PATH=/sources.json explicitly.
# Local:  fallback to parents[5] (loader.py → config → notices → skkuverse_crawler → src → py → repo root).
_SOURCES_JSON = Path(
    os.environ.get("SOURCES_JSON_PATH")
    or str(Path(__file__).resolve().parents[5] / "sources.json")
)

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
}


def load_and_validate() -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = json.loads(
        _SOURCES_JSON.read_text(encoding="utf-8")
    )

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
    ids = [c["id"] for c in configs]
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
        sys.exit(1)

    logger.info("loaded_department_configs", count=len(configs))
    return configs
