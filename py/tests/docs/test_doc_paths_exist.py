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
