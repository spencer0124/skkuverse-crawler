"""Generate all derived artifacts from the SSOT departments.json.

Replaces generate_dept_ids.py. Reads departments.json from repo root,
validates, and produces:

  1. dept_ids.py         — Python DeptId enum
  2. server-departments.json — Server API format
  3. app-departments.ts  — TypeScript enabled dept IDs
  4. docker-crawl-filter.env — CRAWL_DEPT_FILTER env line
  5. coverage-table.md   → docs/department-coverage-analysis.md

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
GENERATED_DIR = REPO_ROOT / "py" / "generated"
DEPT_IDS_PY = (
    REPO_ROOT / "py" / "src" / "skkuverse_crawler"
    / "notices" / "config" / "dept_ids.py"
)
COVERAGE_MD = REPO_ROOT / "docs" / "department-coverage-analysis.md"

# Sibling repos
SERVER_DEPT_JSON = REPO_ROOT.parent / "skkuverse-server" / "features" / "notices" / "departments.json"
APP_DEPT_TS = (
    REPO_ROOT.parent / "skkuverse-app" / "packages" / "shared"
    / "src" / "notices" / "generated-departments.ts"
)

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

VALID_CAMPUSES = {"seoul", "suwon", "both", None}
VALID_APP_CATEGORIES = {
    "dept", "academic", "scholarship", "career",
    "recruitment", "event", "library", "dorm", None,
}

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate(departments: list[dict]) -> list[str]:
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
        if dept.get("appCategory") not in VALID_APP_CATEGORIES:
            errors.append(f"{did}: invalid appCategory '{dept.get('appCategory')}'")

        # crawlEnabled must be bool
        if not isinstance(dept.get("crawlEnabled"), bool):
            errors.append(f"{did}: crawlEnabled must be boolean")

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


def gen_app_ts(departments: list[dict]) -> str:
    enabled = [d["id"] for d in departments if d["crawlEnabled"]]
    lines = [
        "/**",
        " * Auto-generated from departments.json. Do not edit manually.",
        " *",
        " * Regenerate: cd skkuverse-crawler/py && python scripts/generate_artifacts.py",
        " */",
        "",
        "export const NOTICE_AVAILABLE_DEPT_IDS = [",
    ]
    for did in enabled:
        lines.append(f"  '{did}',")
    lines.append("] as const;")
    lines.append("")
    lines.append(
        "export type NoticeAvailableDeptId = "
        "(typeof NOTICE_AVAILABLE_DEPT_IDS)[number];"
    )
    lines.append("")
    return "\n".join(lines)


def gen_docker_env(departments: list[dict]) -> str:
    enabled = [d["id"] for d in departments if d["crawlEnabled"]]
    return f"CRAWL_DEPT_FILTER={','.join(enabled)}\n"


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
        ("seoul", "인문사회과학캠퍼스 (서울)"),
        ("suwon", "자연과학캠퍼스 (수원)"),
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
    if not DEPARTMENTS_JSON.exists():
        print(f"ERROR: {DEPARTMENTS_JSON} not found", file=sys.stderr)
        sys.exit(1)

    with open(DEPARTMENTS_JSON, encoding="utf-8") as f:
        departments = json.load(f)

    # Validate
    errors = validate(departments)
    if errors:
        print("Validation errors:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(departments)} departments from {DEPARTMENTS_JSON.name}")

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

    # 3. app-departments.ts
    app_path = GENERATED_DIR / "app-departments.ts"
    app_path.write_text(gen_app_ts(departments), encoding="utf-8")
    enabled_count = sum(1 for d in departments if d["crawlEnabled"])
    print(f"  [3] app-departments.ts ({enabled_count} enabled)")
    copy_to_sibling(app_path, APP_DEPT_TS, "skkuverse-app")

    # 4. docker-crawl-filter.env
    env_path = GENERATED_DIR / "docker-crawl-filter.env"
    env_path.write_text(gen_docker_env(departments), encoding="utf-8")
    print("  [4] docker-crawl-filter.env")

    # 5. coverage-table.md → docs/
    COVERAGE_MD.write_text(gen_coverage_md(departments), encoding="utf-8")
    print("  [5] docs/department-coverage-analysis.md")

    print("Done.")


if __name__ == "__main__":
    main()
