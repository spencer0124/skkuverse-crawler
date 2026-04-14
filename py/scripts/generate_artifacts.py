"""Generate all derived artifacts from the SSOT config files.

Reads departments.json and categories.json from repo root,
validates cross-references, and produces:

  1. dept_ids.py                    — Python DeptId enum
  2. server-departments.json        — Server API format
  3. docker-crawl-filter.env        — CRAWL_DEPT_FILTER env line
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
DEPARTMENTS_JSON = REPO_ROOT / "departments.json"
CATEGORIES_JSON = REPO_ROOT / "categories.json"
GENERATED_DIR = REPO_ROOT / "py" / "generated"
DEPT_IDS_PY = (
    REPO_ROOT / "py" / "src" / "skkuverse_crawler"
    / "notices" / "config" / "dept_ids.py"
)
COVERAGE_MD = REPO_ROOT / "docs" / "department-coverage-analysis.md"
BY_COLLEGE_MD = REPO_ROOT / "docs" / "departments-by-college.md"
BY_APP_CATEGORY_MD = REPO_ROOT / "docs" / "departments-by-app-category.md"

# Sibling repos
SERVER_DEPT_JSON = REPO_ROOT.parent / "skkuverse-server" / "features" / "notices" / "departments.json"
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
                      "appCategory", "crawlEnabled"):
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

        # crawlEnabled must be bool
        if not isinstance(dept.get("crawlEnabled"), bool):
            errors.append(f"{did}: crawlEnabled must be boolean")

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
            # fixedDeptId must exist and be enabled
            fixed_id = cat.get("fixedDeptId")
            if not fixed_id:
                errors.append(f"category {cid}: fixed mode requires fixedDeptId")
            elif fixed_id not in dept_by_id:
                errors.append(f"category {cid}: fixedDeptId '{fixed_id}' not in departments.json")
            elif not dept_by_id[fixed_id]["crawlEnabled"]:
                errors.append(f"category {cid}: fixedDeptId '{fixed_id}' has crawlEnabled=false")

        elif mode == "picker":
            # maxSelection must be positive int
            max_sel = cat.get("maxSelection")
            if not isinstance(max_sel, int) or max_sel < 1:
                errors.append(f"category {cid}: picker mode requires maxSelection (positive int)")

            # At least one dept matches
            matching = [d for d in departments if d["appCategory"] == cid]
            if not matching:
                errors.append(f"category {cid}: picker matches 0 departments")

    # Every non-null appCategory in departments must have a category entry
    for app_cat in sorted(dept_app_cats):
        if app_cat not in cat_ids:
            errors.append(
                f"appCategory '{app_cat}' used in departments.json "
                f"but has no entry in categories.json"
            )

    return errors


# ---------------------------------------------------------------------------
# Artifact generators
# ---------------------------------------------------------------------------
def gen_dept_ids(departments: list[dict]) -> str:
    lines = [
        '"""Auto-generated from departments.json. Do not edit manually.',
        "",
        "Regenerate: cd py && python scripts/generate_artifacts.py",
        '"""',
        "",
        "from enum import Enum",
        "",
        "",
        "class DeptId(str, Enum):",
    ]
    for dept in departments:
        enum_name = dept["id"].replace("-", "_").upper()
        lines.append(f'    {enum_name} = "{dept["id"]}"')
    lines.append("")
    return "\n".join(lines)


def gen_server_json(departments: list[dict]) -> str:
    entries = []
    for dept in departments:
        has_cat, has_author = STRATEGY_FEATURES[dept["strategy"]]
        entries.append({
            "id": dept["id"],
            "name": dept["name"],
            "campus": dept["campus"],
            "college": dept["college"],
            "appCategory": dept["appCategory"],
            "noticeAvailable": dept["crawlEnabled"],
            "hasCategory": has_cat,
            "hasAuthor": has_author,
        })
    return json.dumps(entries, ensure_ascii=False, indent=2) + "\n"


def gen_docker_env(departments: list[dict]) -> str:
    enabled = [d["id"] for d in departments if d["crawlEnabled"]]
    return f"CRAWL_DEPT_FILTER={','.join(enabled)}\n"


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
                "deptId": cat["fixedDeptId"],
            })
        else:  # picker
            dept_ids = [
                d["id"] for d in departments
                if d["appCategory"] == cat["id"] and d["crawlEnabled"]
            ]
            entries.append({
                "id": cat["id"],
                "label": cat["label"],
                "tabMode": "picker",
                "deptIds": dept_ids,
                "maxSelection": cat["maxSelection"],
            })
    return json.dumps(entries, ensure_ascii=False, indent=2) + "\n"


def gen_coverage_md(departments: list[dict]) -> str:
    lines = [
        "<!-- Auto-generated from departments.json. Do not edit manually. -->",
        "<!-- Regenerate: cd py && python scripts/generate_artifacts.py -->",
        "",
        "# 크롤링 학과/기관 전수 분류 + 커버리지 분석",
        "",
        f"> departments.json 기준 {len(departments)}개 엔트리",
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
                enabled = "O" if d["crawlEnabled"] else ""
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
                enabled = "O" if d["crawlEnabled"] else ""
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
            enabled = "O" if d["crawlEnabled"] else ""
            lines.append(f"| `{d['id']}` | {d['name']} | {enabled} |")
        lines.append("")

    # Summary
    enabled_count = sum(1 for d in departments if d["crawlEnabled"])
    lines.append("## 요약")
    lines.append("")
    lines.append(f"- 총 엔트리: {len(departments)}")
    lines.append(f"- 크롤링 활성: {enabled_count}")
    lines.append(f"- 전략 수: {len(strat_counts)}")
    lines.append("")

    return "\n".join(lines)


def gen_by_college_md(departments: list[dict]) -> str:
    lines = [
        "<!-- Auto-generated from departments.json. Do not edit manually. -->",
        "<!-- Regenerate: cd py && python scripts/generate_artifacts.py -->",
        "",
        "# 단과대학별 학과 목록",
        "",
        f"> departments.json 기준 {len(departments)}개 엔트리",
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
            enabled = "O" if d["crawlEnabled"] else ""
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
        "<!-- Auto-generated from departments.json. Do not edit manually. -->",
        "<!-- Regenerate: cd py && python scripts/generate_artifacts.py -->",
        "",
        "# 앱 카테고리별 학과 목록",
        "",
        f"> departments.json 기준 {len(departments)}개 엔트리",
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
            enabled = "O" if d["crawlEnabled"] else ""
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
    for path in (DEPARTMENTS_JSON, CATEGORIES_JSON):
        if not path.exists():
            print(f"ERROR: {path} not found", file=sys.stderr)
            sys.exit(1)

    with open(DEPARTMENTS_JSON, encoding="utf-8") as f:
        departments = json.load(f)
    with open(CATEGORIES_JSON, encoding="utf-8") as f:
        categories = json.load(f)

    # Derive valid appCategories from categories.json
    valid_app_categories: set[str | None] = {c["id"] for c in categories} | {None}

    # Validate
    errors = validate_departments(departments, valid_app_categories)
    errors += validate_categories(categories, departments)
    if errors:
        print("Validation errors:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(departments)} departments, {len(categories)} categories")

    # Ensure generated/ exists
    GENERATED_DIR.mkdir(exist_ok=True)

    # 1. dept_ids.py
    DEPT_IDS_PY.write_text(gen_dept_ids(departments), encoding="utf-8")
    print(f"  [1] dept_ids.py ({len(departments)} enums)")

    # 2. server-departments.json
    server_path = GENERATED_DIR / "server-departments.json"
    server_path.write_text(gen_server_json(departments), encoding="utf-8")
    print("  [2] server-departments.json")
    copy_to_sibling(server_path, SERVER_DEPT_JSON, "skkuverse-server")

    # 3. docker-crawl-filter.env
    env_path = GENERATED_DIR / "docker-crawl-filter.env"
    env_path.write_text(gen_docker_env(departments), encoding="utf-8")
    print("  [3] docker-crawl-filter.env")

    # 4. coverage-table.md → docs/
    COVERAGE_MD.write_text(gen_coverage_md(departments), encoding="utf-8")
    print("  [4] docs/department-coverage-analysis.md")

    # 5. departments-by-college.md → docs/
    BY_COLLEGE_MD.write_text(gen_by_college_md(departments), encoding="utf-8")
    print("  [5] docs/departments-by-college.md")

    # 6. departments-by-app-category.md → docs/
    BY_APP_CATEGORY_MD.write_text(
        gen_by_app_category_md(departments, categories), encoding="utf-8",
    )
    print("  [6] docs/departments-by-app-category.md")

    # 7. server-categories.json
    cat_path = GENERATED_DIR / "server-categories.json"
    cat_path.write_text(
        gen_server_categories(categories, departments), encoding="utf-8",
    )
    print("  [7] server-categories.json")
    copy_to_sibling(cat_path, SERVER_CAT_JSON, "skkuverse-server")

    print("Done.")


if __name__ == "__main__":
    main()
