"""Generate all derived artifacts from the SSOT config files.

Reads sources.json and categories.json from repo root,
validates cross-references, and produces:

  1. source_ids.py                  — Python SourceId enum
  2. server-sources.json            — Server API format
  3. docker-crawl-filter.env        — CRAWL_SOURCE_FILTER env line
  4. coverage-table.md              → docs/department-coverage-analysis.md
  5. departments-by-college.md      → docs/departments-by-college.md
  6. departments-by-app-category.md → docs/departments-by-app-category.md
  7. server-categories.json         — Server-driven tab config for app

Usage:
    cd py
    python scripts/generate_artifacts.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SOURCES_JSON = REPO_ROOT / "sources.json"
CATEGORIES_JSON = REPO_ROOT / "categories.json"
GENERATED_DIR = REPO_ROOT / "py" / "generated"
SOURCE_IDS_PY = (
    REPO_ROOT / "py" / "src" / "skkuverse_crawler"
    / "notices" / "config" / "source_ids.py"
)
COVERAGE_MD = REPO_ROOT / "docs" / "department-coverage-analysis.md"
BY_COLLEGE_MD = REPO_ROOT / "docs" / "departments-by-college.md"
BY_APP_CATEGORY_MD = REPO_ROOT / "docs" / "departments-by-app-category.md"

# Sibling repos
SERVER_SOURCES_JSON = REPO_ROOT.parent / "skkuverse-server" / "features" / "notices" / "sources.json"
SERVER_CAT_JSON = REPO_ROOT.parent / "skkuverse-server" / "features" / "notices" / "categories.json"

# ---------------------------------------------------------------------------
# Strategy → hasCategory / hasAuthor mapping
# ---------------------------------------------------------------------------
STRATEGY_FEATURES: dict[str, tuple[bool, bool]] = {
    "skku-standard":   (True,  True),
    "pyxis-api":       (True,  False),
    "jsp-dorm":        (True,  False),
    "custom-php":      (True,  False),
    "gnuboard":        (False, True),
    "gnuboard-custom": (False, True),
    "skkumed-asp":     (False, True),
    "wordpress-api":   (False, False),
}

VALID_CAMPUSES = {"hssc", "nsc", "both", None}
VALID_TAB_MODES = {"fixed", "picker"}
VALID_CAMPUS_DEFAULT_KEYS = {"hssc", "nsc"}

# excludeReason enum keys. Mirrored on the client as i18n keys
# (onboarding.unsupportedDept.reason.<key>). Adding a new reason requires
# updating the client translations in the same release.
VALID_EXCLUDE_REASONS = {
    "loginRequired",
    "noWebsite",
    "externalSystem",
    "accessRestricted",
    "temporarilyUnavailable",
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_departments(
    departments: list[dict],
    valid_app_categories: set[str | None],
) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()

    for i, dept in enumerate(departments):
        did = dept.get("id", f"<index {i}>")

        # Required fields
        for field in ("id", "name", "strategy", "campus", "college",
                      "appCategory", "crawlAvailable", "crawlEnabled",
                      "excludeReason"):
            if field not in dept:
                errors.append(f"{did}: missing required field '{field}'")

        # Duplicate ID
        if did in seen_ids:
            errors.append(f"{did}: duplicate ID")
        seen_ids.add(did)

        # Known strategy
        strategy = dept.get("strategy")
        if strategy and strategy not in STRATEGY_FEATURES:
            errors.append(f"{did}: unknown strategy '{strategy}'")

        # Valid enum values
        if dept.get("campus") not in VALID_CAMPUSES:
            errors.append(f"{did}: invalid campus '{dept.get('campus')}'")
        if dept.get("appCategory") not in valid_app_categories:
            errors.append(f"{did}: invalid appCategory '{dept.get('appCategory')}'")

        # crawlAvailable / crawlEnabled must be bool
        if not isinstance(dept.get("crawlAvailable"), bool):
            errors.append(f"{did}: crawlAvailable must be boolean")
        if not isinstance(dept.get("crawlEnabled"), bool):
            errors.append(f"{did}: crawlEnabled must be boolean")

        # excludeReason: must be a known enum key, or null
        reason = dept.get("excludeReason")
        if reason is not None and reason not in VALID_EXCLUDE_REASONS:
            errors.append(
                f"{did}: invalid excludeReason '{reason}' "
                f"(allowed: {sorted(VALID_EXCLUDE_REASONS)} or null)"
            )

        # Three-rule semantic consistency:
        # crawlAvailable | excludeReason | crawlEnabled
        # ───────────────┼───────────────┼─────────────
        # true           | null          | * (any)             ← normal, valid
        # false          | non-null key  | false               ← intentionally unsupported
        # any other combination is a contradiction.
        avail = dept.get("crawlAvailable")
        if avail is False and reason is None:
            errors.append(
                f"{did}: crawlAvailable=false requires non-null excludeReason "
                f"(unsupported depts must declare a reason)"
            )
        if avail is True and reason is not None:
            errors.append(
                f"{did}: crawlAvailable=true must have null excludeReason "
                f"(crawlable depts cannot have an exclusion reason)"
            )
        if avail is False and dept.get("crawlEnabled") is True:
            errors.append(
                f"{did}: crawlAvailable=false forbids crawlEnabled=true "
                f"(unsupported source cannot be operationally enabled)"
            )

    return errors


def validate_categories(
    categories: list[dict],
    departments: list[dict],
) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    dept_by_id = {d["id"]: d for d in departments}
    dept_app_cats = {d["appCategory"] for d in departments if d["appCategory"] is not None}
    cat_ids = {c["id"] for c in categories}

    for i, cat in enumerate(categories):
        cid = cat.get("id", f"<index {i}>")

        # Duplicate ID
        if cid in seen_ids:
            errors.append(f"category {cid}: duplicate ID")
        seen_ids.add(cid)

        # tabMode
        mode = cat.get("tabMode")
        if mode not in VALID_TAB_MODES:
            errors.append(f"category {cid}: invalid tabMode '{mode}'")

        # Label
        label = cat.get("label", {})
        for lang in ("ko", "en"):
            if lang not in label:
                errors.append(f"category {cid}: missing label.{lang}")

        if mode == "fixed":
            # fixedSourceId must exist and be structurally crawlable
            # (operational pause via crawlEnabled=false is fine — fixed tab
            # still renders, just with stale data until cron resumes).
            fixed_id = cat.get("fixedSourceId")
            if not fixed_id:
                errors.append(f"category {cid}: fixed mode requires fixedSourceId")
            elif fixed_id not in dept_by_id:
                errors.append(f"category {cid}: fixedSourceId '{fixed_id}' not in sources.json")
            elif not dept_by_id[fixed_id]["crawlAvailable"]:
                errors.append(
                    f"category {cid}: fixedSourceId '{fixed_id}' has "
                    f"crawlAvailable=false (unsupported source can't anchor a fixed tab)"
                )

        elif mode == "picker":
            # maxSelection must be positive int
            max_sel = cat.get("maxSelection")
            if not isinstance(max_sel, int) or max_sel < 1:
                errors.append(f"category {cid}: picker mode requires maxSelection (positive int)")

            # At least one dept matches
            matching = [d for d in departments if d["appCategory"] == cid]
            if not matching:
                errors.append(f"category {cid}: picker matches 0 departments")

            # Default-seed eligibility: only depts that actually crawl.
            # Unsupported depts (crawlAvailable=false) must NOT be defaulted —
            # users would see a permanently empty notice list.
            enabled_ids = {
                d["id"] for d in departments
                if d["appCategory"] == cid
                and d["crawlAvailable"] and d["crawlEnabled"]
            }

            # Optional defaultIds (common defaults — seeded for every campus)
            defaults = cat.get("defaultIds")
            if defaults is not None:
                if not isinstance(defaults, list):
                    errors.append(f"category {cid}: defaultIds must be array")
                else:
                    for did in defaults:
                        if did not in enabled_ids:
                            errors.append(
                                f"category {cid}: defaultId '{did}' "
                                f"not in enabled matching depts"
                            )

            # Optional campusDefaultIds (per-campus additional defaults)
            campus_defaults = cat.get("campusDefaultIds")
            if campus_defaults is not None:
                if not isinstance(campus_defaults, dict):
                    errors.append(
                        f"category {cid}: campusDefaultIds must be object"
                    )
                else:
                    for campus_key, ids in campus_defaults.items():
                        if campus_key not in VALID_CAMPUS_DEFAULT_KEYS:
                            errors.append(
                                f"category {cid}: campusDefaultIds key "
                                f"'{campus_key}' must be one of "
                                f"{sorted(VALID_CAMPUS_DEFAULT_KEYS)}"
                            )
                            continue
                        if not isinstance(ids, list):
                            errors.append(
                                f"category {cid}: campusDefaultIds.{campus_key} "
                                f"must be array"
                            )
                            continue
                        for did in ids:
                            if did not in enabled_ids:
                                errors.append(
                                    f"category {cid}: campusDefaultIds."
                                    f"{campus_key} '{did}' not in enabled matching depts"
                                )
                        # Per-campus seed cap: union of common + this campus
                        # must not exceed maxSelection. Keeps the picker UI's
                        # cap intact regardless of which campus the user picks.
                        if isinstance(max_sel, int) and isinstance(defaults, list):
                            seed = set(defaults) | set(ids)
                            if len(seed) > max_sel:
                                errors.append(
                                    f"category {cid}: seed for campus "
                                    f"'{campus_key}' has {len(seed)} ids > "
                                    f"maxSelection {max_sel}"
                                )

    # Every non-null appCategory in departments must have a category entry
    for app_cat in sorted(dept_app_cats):
        if app_cat not in cat_ids:
            errors.append(
                f"appCategory '{app_cat}' used in sources.json "
                f"but has no entry in categories.json"
            )

    return errors


# ---------------------------------------------------------------------------
# Artifact generators
# ---------------------------------------------------------------------------
def gen_source_ids(sources: list[dict]) -> str:
    lines = [
        '"""Auto-generated from sources.json. Do not edit manually.',
        "",
        "Regenerate: cd py && python scripts/generate_artifacts.py",
        '"""',
        "",
        "from enum import Enum",
        "",
        "",
        "class SourceId(str, Enum):",
    ]
    for source in sources:
        enum_name = source["id"].replace("-", "_").upper()
        lines.append(f'    {enum_name} = "{source["id"]}"')
    lines.append("")
    return "\n".join(lines)


def gen_sources_json(sources: list[dict]) -> str:
    """Server-facing artifact (skkuverse-server/features/notices/sources.json).

    Carries crawler-domain field names (crawlAvailable, excludeReason) through;
    the server's tabConfig.js maps these to the client-friendly response shape
    (e.g. crawlAvailable → noticeAvailable) at API boundary.
    """
    entries = []
    for source in sources:
        has_cat, has_author = STRATEGY_FEATURES[source["strategy"]]
        entries.append({
            "id": source["id"],
            "name": source["name"],
            "campus": source["campus"],
            "college": source["college"],
            "appCategory": source["appCategory"],
            "crawlAvailable": source["crawlAvailable"],
            "excludeReason": source["excludeReason"],
            "hasCategory": has_cat,
            "hasAuthor": has_author,
        })
    return json.dumps(entries, ensure_ascii=False, indent=2) + "\n"


def gen_docker_env(departments: list[dict]) -> str:
    # Cron actually crawls only when BOTH structurally available AND
    # operationally enabled. Either flag false → skip.
    enabled = [
        d["id"] for d in departments
        if d["crawlAvailable"] and d["crawlEnabled"]
    ]
    return f"CRAWL_SOURCE_FILTER={','.join(enabled)}\n"


def gen_server_categories(
    categories: list[dict],
    departments: list[dict],
) -> str:
    entries = []
    for cat in categories:
        if cat["tabMode"] == "fixed":
            entries.append({
                "id": cat["id"],
                "label": cat["label"],
                "tabMode": "fixed",
                "sourceId": cat["fixedSourceId"],
            })
        else:  # picker
            # Picker visibility: crawlable OR intentionally unsupported.
            # Unsupported entries stay so the client can render them greyed
            # out and explain *why* (excludeReason). Operational pause
            # (crawlEnabled=false but crawlAvailable=true) keeps them visible.
            source_ids = [
                d["id"] for d in departments
                if d["appCategory"] == cat["id"]
                and (d["crawlAvailable"] or d["excludeReason"] is not None)
            ]
            entry: dict = {
                "id": cat["id"],
                "label": cat["label"],
                "tabMode": "picker",
                "sourceIds": source_ids,
                "maxSelection": cat["maxSelection"],
            }
            if "defaultIds" in cat:
                entry["defaultIds"] = cat["defaultIds"]
            if "campusDefaultIds" in cat:
                entry["campusDefaultIds"] = cat["campusDefaultIds"]
            entries.append(entry)
    return json.dumps(entries, ensure_ascii=False, indent=2) + "\n"


def gen_coverage_md(departments: list[dict]) -> str:
    lines = [
        "<!-- Auto-generated from sources.json. Do not edit manually. -->",
        "<!-- Regenerate: cd py && python scripts/generate_artifacts.py -->",
        "",
        "# 크롤링 학과/기관 전수 분류 + 커버리지 분석",
        "",
        f"> sources.json 기준 {len(departments)}개 엔트리",
        "",
    ]

    # Strategy distribution
    strat_counts: dict[str, int] = {}
    for d in departments:
        s = d["strategy"]
        strat_counts[s] = strat_counts.get(s, 0) + 1

    lines.append("## 전략별 분포")
    lines.append("")
    lines.append("| 전략 | 수 |")
    lines.append("|------|----|")
    for s, c in sorted(strat_counts.items(), key=lambda x: -x[1]):
        lines.append(f"| `{s}` | {c} |")
    lines.append("")

    # By campus → college → departments
    for campus_val, campus_label in [
        ("hssc", "인문사회과학캠퍼스"),
        ("nsc", "자연과학캠퍼스"),
    ]:
        campus_depts = [d for d in departments if d["campus"] == campus_val]
        if not campus_depts:
            continue

        lines.append(f"## {campus_label}")
        lines.append("")

        # Group by college
        colleges: dict[str | None, list[dict]] = {}
        for d in campus_depts:
            col = d["college"]
            colleges.setdefault(col, []).append(d)

        for college, depts in colleges.items():
            college_label = college or "(소속 없음)"
            lines.append(f"### {college_label}")
            lines.append("")
            lines.append("| ID | 이름 | 전략 | 활성 |")
            lines.append("|----|------|------|:----:|")
            for d in depts:
                enabled = "O" if d["crawlAvailable"] and d["crawlEnabled"] else ""
                strategy = d["strategy"] if d["strategy"] != "skku-standard" else ""
                lines.append(f"| `{d['id']}` | {d['name']} | {strategy} | {enabled} |")
            lines.append("")

    # Both campus (본부/기관)
    both_depts = [d for d in departments if d["campus"] == "both"]
    if both_depts:
        lines.append("## 양캠퍼스 공통")
        lines.append("")

        # Group by appCategory
        by_cat: dict[str | None, list[dict]] = {}
        for d in both_depts:
            cat = d["appCategory"]
            by_cat.setdefault(cat, []).append(d)

        for cat, depts in by_cat.items():
            cat_label = cat or "미분류"
            lines.append(f"### {cat_label}")
            lines.append("")
            lines.append("| ID | 이름 | 활성 |")
            lines.append("|----|------|:----:|")
            for d in depts:
                enabled = "O" if d["crawlAvailable"] and d["crawlEnabled"] else ""
                lines.append(f"| `{d['id']}` | {d['name']} | {enabled} |")
            lines.append("")

    # Null campus
    null_campus = [d for d in departments if d["campus"] is None]
    if null_campus:
        lines.append("## 캠퍼스 미지정")
        lines.append("")
        lines.append("| ID | 이름 | 활성 |")
        lines.append("|----|------|:----:|")
        for d in null_campus:
            enabled = "O" if d["crawlAvailable"] and d["crawlEnabled"] else ""
            lines.append(f"| `{d['id']}` | {d['name']} | {enabled} |")
        lines.append("")

    # Summary
    enabled_count = sum(1 for d in departments if d["crawlAvailable"] and d["crawlEnabled"])
    lines.append("## 요약")
    lines.append("")
    lines.append(f"- 총 엔트리: {len(departments)}")
    lines.append(f"- 크롤링 활성: {enabled_count}")
    lines.append(f"- 전략 수: {len(strat_counts)}")
    lines.append("")

    return "\n".join(lines)


def gen_by_college_md(departments: list[dict]) -> str:
    lines = [
        "<!-- Auto-generated from sources.json. Do not edit manually. -->",
        "<!-- Regenerate: cd py && python scripts/generate_artifacts.py -->",
        "",
        "# 단과대학별 학과 목록",
        "",
        f"> sources.json 기준 {len(departments)}개 엔트리",
        "",
    ]

    # Group by college
    colleges: dict[str | None, list[dict]] = {}
    for d in departments:
        colleges.setdefault(d["college"], []).append(d)

    # Sort: named colleges alphabetically, None last
    sorted_colleges = sorted(
        colleges.items(),
        key=lambda x: (x[0] is None, x[0] or ""),
    )

    for college, depts in sorted_colleges:
        label = college or "미소속"
        lines.append(f"## {label}")
        lines.append("")
        lines.append("| ID | 이름 | 캠퍼스 | 전략 | 활성 |")
        lines.append("|----|------|--------|------|:----:|")
        for d in depts:
            campus = d["campus"] or ""
            strategy = d["strategy"] if d["strategy"] != "skku-standard" else ""
            enabled = "O" if d["crawlAvailable"] and d["crawlEnabled"] else ""
            lines.append(
                f"| `{d['id']}` | {d['name']} | {campus} | {strategy} | {enabled} |"
            )
        lines.append("")

    return "\n".join(lines)


def gen_by_app_category_md(
    departments: list[dict],
    categories: list[dict],
) -> str:
    lines = [
        "<!-- Auto-generated from sources.json. Do not edit manually. -->",
        "<!-- Regenerate: cd py && python scripts/generate_artifacts.py -->",
        "",
        "# 앱 카테고리별 학과 목록",
        "",
        f"> sources.json 기준 {len(departments)}개 엔트리",
        "",
    ]

    # Group by appCategory
    by_cat: dict[str | None, list[dict]] = {}
    for d in departments:
        by_cat.setdefault(d["appCategory"], []).append(d)

    # Display order derived from categories.json
    category_order: list[tuple[str | None, str]] = [
        (c["id"], f"{c['label']['ko']} ({c['id']})") for c in categories
    ]
    category_order.append((None, "미분류"))

    for cat, label in category_order:
        depts = by_cat.get(cat)
        if not depts:
            continue
        lines.append(f"## {label}")
        lines.append("")
        lines.append("| ID | 이름 | 캠퍼스 | 전략 | 활성 |")
        lines.append("|----|------|--------|------|:----:|")
        for d in depts:
            campus = d["campus"] or ""
            strategy = d["strategy"] if d["strategy"] != "skku-standard" else ""
            enabled = "O" if d["crawlAvailable"] and d["crawlEnabled"] else ""
            lines.append(
                f"| `{d['id']}` | {d['name']} | {campus} | {strategy} | {enabled} |"
            )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sibling repo copy
# ---------------------------------------------------------------------------
def copy_to_sibling(src: Path, dst: Path, label: str) -> None:
    if dst.parent.exists():
        shutil.copy2(src, dst)
        print(f"  -> Copied to {label}: {dst}")
    else:
        print(f"  -- Skipped {label} (directory not found)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    # Load sources
    for path in (SOURCES_JSON, CATEGORIES_JSON):
        if not path.exists():
            print(f"ERROR: {path} not found", file=sys.stderr)
            sys.exit(1)

    with open(SOURCES_JSON, encoding="utf-8") as f:
        sources = json.load(f)
    with open(CATEGORIES_JSON, encoding="utf-8") as f:
        categories = json.load(f)

    # Derive valid appCategories from categories.json
    valid_app_categories: set[str | None] = {c["id"] for c in categories} | {None}

    # Validate
    errors = validate_departments(sources, valid_app_categories)
    errors += validate_categories(categories, sources)
    if errors:
        print("Validation errors:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(sources)} sources, {len(categories)} categories")

    # Ensure generated/ exists
    GENERATED_DIR.mkdir(exist_ok=True)

    # 1. source_ids.py
    SOURCE_IDS_PY.write_text(gen_source_ids(sources), encoding="utf-8")
    print(f"  [1] source_ids.py ({len(sources)} enums)")

    # 2. server-sources.json
    server_path = GENERATED_DIR / "server-sources.json"
    server_path.write_text(gen_sources_json(sources), encoding="utf-8")
    print("  [2] server-sources.json")
    copy_to_sibling(server_path, SERVER_SOURCES_JSON, "skkuverse-server")

    # 3. docker-crawl-filter.env
    env_path = GENERATED_DIR / "docker-crawl-filter.env"
    env_path.write_text(gen_docker_env(sources), encoding="utf-8")
    print("  [3] docker-crawl-filter.env")

    # 4. coverage-table.md → docs/
    COVERAGE_MD.write_text(gen_coverage_md(sources), encoding="utf-8")
    print("  [4] docs/department-coverage-analysis.md")

    # 5. departments-by-college.md → docs/
    BY_COLLEGE_MD.write_text(gen_by_college_md(sources), encoding="utf-8")
    print("  [5] docs/departments-by-college.md")

    # 6. departments-by-app-category.md → docs/
    BY_APP_CATEGORY_MD.write_text(
        gen_by_app_category_md(sources, categories), encoding="utf-8",
    )
    print("  [6] docs/departments-by-app-category.md")

    # 7. server-categories.json
    cat_path = GENERATED_DIR / "server-categories.json"
    cat_path.write_text(
        gen_server_categories(categories, sources), encoding="utf-8",
    )
    print("  [7] server-categories.json")
    copy_to_sibling(cat_path, SERVER_CAT_JSON, "skkuverse-server")

    print("Done.")


if __name__ == "__main__":
    main()
