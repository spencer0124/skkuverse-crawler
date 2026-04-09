"""Generate notices/config/dept_ids.py from departments.json.

Usage:
    cd py
    python scripts/generate_dept_ids.py
"""

from __future__ import annotations

import json
from pathlib import Path

DEPARTMENTS_JSON = (
    Path(__file__).resolve().parent.parent
    / "src" / "skkuverse_crawler" / "notices" / "config" / "departments.json"
)
OUTPUT = DEPARTMENTS_JSON.parent / "dept_ids.py"


def id_to_enum_name(dept_id: str) -> str:
    return dept_id.replace("-", "_").upper()


def main() -> None:
    with open(DEPARTMENTS_JSON, encoding="utf-8") as f:
        departments = json.load(f)

    lines = [
        '"""Auto-generated from departments.json. Do not edit manually.',
        "",
        "Regenerate: cd py && python scripts/generate_dept_ids.py",
        '"""',
        "",
        "from enum import Enum",
        "",
        "",
        "class DeptId(str, Enum):",
    ]

    for dept in departments:
        dept_id = dept["id"]
        enum_name = id_to_enum_name(dept_id)
        lines.append(f'    {enum_name} = "{dept_id}"')

    lines.append("")  # trailing newline

    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Generated {OUTPUT} ({len(departments)} departments)")


if __name__ == "__main__":
    main()
