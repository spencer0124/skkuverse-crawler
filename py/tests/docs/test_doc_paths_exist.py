"""Source paths named in the docs must exist.

PR 4 moved `notices/` under `modules/` and PR 7 moved four more trees into
`plugins/`. Roughly thirty documentation lines kept pointing at the old
locations for months, because nothing reads a path in a Markdown file.
Fixing them once buys a few months; this buys the property.

Deliberately narrow. It checks `py/src/...` paths only — the ones that
move when the package is refactored — and does not attempt to validate
symbols after `::`, line numbers (deliberately purged; they were the same
rot in a form even harder to spot) or Markdown links.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[3]
DOC_DIRS = ("docs",)
DOC_FILES = ("README.md", "CLAUDE.md")

SOURCE_PATH = re.compile(r"py/src/skkuverse_crawler/[\w./*-]+")

# Paths that are allowed not to exist, with the reason. History is the
# only sanctioned category: an incident write-up saying which file the fix
# landed in is a statement about the past, and rewriting it to today's
# layout would make it false. Those lines should name the current home
# alongside the old one.
#
# Empty today, and that is the honest state — every historical reference in
# the docs currently uses a bare filename (`dedup.py`) rather than a full
# `py/src/...` path, so none of them reach this scan. Entries go here only
# when a real one shows up. Note that `_referenced_paths` strips trailing
# punctuation, so an entry must be written in its POST-strip form:
# `.../notices/...` normalizes to `.../notices/` before the lookup.
HISTORICAL: set[str] = set()


def _doc_files() -> list[Path]:
    found = [p for d in DOC_DIRS for p in (REPO_ROOT / d).rglob("*.md")]
    found += [REPO_ROOT / f for f in DOC_FILES if (REPO_ROOT / f).is_file()]
    return sorted(found)


def _referenced_paths(doc: Path) -> set[str]:
    return {m.group(0).rstrip(".,)`") for m in SOURCE_PATH.finditer(doc.read_text())}


@pytest.mark.parametrize("doc", _doc_files(), ids=lambda p: str(p.name))
def test_source_paths_named_in_docs_exist(doc: Path):
    dead = []
    for ref in sorted(_referenced_paths(doc)):
        if ref in HISTORICAL:
            continue
        # A trailing glob names a directory's contents.
        target = REPO_ROOT / (ref.rsplit("/", 1)[0] if ref.endswith("*.py") else ref)
        if not target.exists():
            dead.append(ref)

    assert not dead, (
        f"{doc.relative_to(REPO_ROOT)} points at paths that no longer exist: {dead}. "
        f"Update them, or — if the line is describing history and the old name is "
        f"the point — name the current home alongside and add the old one to HISTORICAL."
    )


# ── Retired layouts ──────────────────────────────────────────────────
# The scan above only sees full `py/src/...` paths, and almost no doc line
# writes one — prose says `plugins/health/store.py`. That blind spot is
# where the rot actually lived: on 2026-08-04 every stale line found was a
# bare path, and the full-path scan had been green the whole time.
#
# So this second scan names the dead layouts directly. It cannot catch a
# path that goes stale in some *future* move — only the full-path scan
# generalizes — but it does pin the ones that already rotted once, which
# is the population that demonstrably comes back.
RETIRED: dict[str, str] = {
    "crawl_health/": "plugins/health/",
    "notices_summary/": "plugins/ai_summary/",
    "notices_embedding/": "(deleted — adr-007)",
    "dispatch_client.py": "plugins/dispatch/client.py",
    "net/fetcher.py": "shared/fetcher.py",
    "core/logging.py": "shared/logger.py",
    "core/simple.py": "modules/notices/simple.py",
    "core/content/": "modules/notices/stages.py",
    "shared/config.py": "env.py + core/settings.py",
    "modules/base.py": "core/module.py",
    "modules/registry.py": "core/registry.py",
    "notices/dedup.py": "modules/notices/policy.py",
    "notices/backfill.py": "plugins/mongo/work_seed.py",
}

# A retired name is fine when the line also says where the code lives now
# — that is a statement about history, not a stale pointer. These are the
# lines that cannot do that: design sketches and migration checklists,
# where the old layout *is* the content. Keyed by (doc name, retired path)
# so a new occurrence elsewhere still fails.
SANCTIONED: set[tuple[str, str]] = {
    # §레이아웃 is the pre-implementation sketch, flagged as such in the
    # doc's own header table.
    ("core-plugin-architecture.md", "net/fetcher.py"),
    ("core-plugin-architecture.md", "core/content/"),
    ("core-plugin-architecture.md", "notices_summary/"),
    ("core-plugin-architecture.md", "crawl_health/"),
    # PR checklists record the tree as it stood when the work was planned.
    ("core-plugin-plan.md", "dispatch_client.py"),
    ("core-plugin-plan.md", "core/simple.py"),
    ("core-plugin-plan.md", "core/content/"),
    ("core-plugin-plan.md", "shared/config.py"),
    ("core-plugin-plan.md", "modules/base.py"),
    ("core-plugin-plan.md", "modules/registry.py"),
    # Names a module deliberately NOT created — the sentence's whole point
    # is that the work fits on the existing write paths without one.
    ("search-mcp-plan.md", "notices_embedding/"),
    # ADR-006/007 are decision records; rewriting them falsifies the record.
    ("adr-006-core-plugin-split.md", "core/simple.py"),
    ("adr-006-core-plugin-split.md", "shared/config.py"),
    ("adr-006-core-plugin-split.md", "modules/base.py"),
    ("adr-007-atlas-auto-embedding.md", "notices_embedding/"),
}

# `(?<![\w/])` keeps `notices/dedup.py` from matching inside
# `modules/notices/dedup.py`, and `crawl_health/` from matching the
# MongoDB collection named `crawl_health` (no trailing slash).
_RETIRED_RE = {
    dead: re.compile(r"(?<![\w/])" + re.escape(dead)) for dead in RETIRED
}


def _live_paths() -> set[str]:
    pkg = REPO_ROOT / "py/src/skkuverse_crawler"
    out = set()
    for p in pkg.rglob("*"):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(pkg).as_posix()
        out.add(rel + "/" if p.is_dir() else rel)
    return out


@pytest.mark.parametrize("doc", _doc_files(), ids=lambda p: str(p.name))
def test_docs_do_not_point_at_retired_layouts(doc: Path):
    live = _live_paths()
    offenders = []
    for lineno, line in enumerate(doc.read_text().splitlines(), 1):
        for dead, now in RETIRED.items():
            if not _RETIRED_RE[dead].search(line):
                continue
            if (doc.name, dead) in SANCTIONED:
                continue
            # Naming any current location on the same line is the
            # "당시 X, 현재 Y" pattern the docs already use.
            if any(p in line for p in live if len(p) > 6):
                continue
            offenders.append(f"{lineno}: {dead!r} (now {now})")

    assert not offenders, (
        f"{doc.relative_to(REPO_ROOT)} points at retired layouts:\n  "
        + "\n  ".join(offenders)
        + "\nName the current home on the same line, or add (doc, path) to "
        "SANCTIONED if the old layout is the point (design sketch, ADR)."
    )


def test_the_scan_finds_paths_at_all():
    """Guards the regex, which is the failure mode of every grep-based
    check: a pattern that matches nothing makes every test above pass
    vacuously.

    Asserted against a path that is certainly written down rather than a
    count — a threshold would have to be lowered every time a doc is
    trimmed, and the version that had to be lowered once is the version
    nobody trusts.
    """
    everything = {ref for doc in _doc_files() for ref in _referenced_paths(doc)}
    assert "py/src/skkuverse_crawler/modules/notices/models.py" in everything, (
        f"the path regex matched {len(everything)} distinct paths but not the Notice "
        f"model, which the schema docs point at by full path — the pattern is broken"
    )
