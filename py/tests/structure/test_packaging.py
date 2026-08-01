"""The packaging contract, checked without building anything.

The plan's ⚠️ for this PR was that splitting motor into an extra and
forgetting the Dockerfile produces an image that builds, boots, logs
cleanly, and writes nothing. Reading both files and comparing them turns
that from a thing you must remember into a thing that fails the suite.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

PY_ROOT = Path(__file__).parents[2]
PYPROJECT = PY_ROOT / "pyproject.toml"
DOCKERFILE = PY_ROOT / "Dockerfile"

# Extras that exist for developing/aggregating, not for running in production.
NON_RUNTIME_EXTRAS = {"dev", "all"}


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text())


def _extras() -> dict[str, list[str]]:
    return _pyproject()["project"]["optional-dependencies"]


def _base_dependency_names() -> set[str]:
    return {
        re.split(r"[><=!~\[]", spec)[0].strip().lower()
        for spec in _pyproject()["project"]["dependencies"]
    }


def _uv_sync_extra_sets() -> list[set[str]]:
    """The --extra flags of every `uv sync` line in the Dockerfile."""
    text = DOCKERFILE.read_text()
    # Join continuations so a multi-line RUN reads as one command.
    text = re.sub(r"\\\s*\n\s*", " ", text)
    return [
        set(re.findall(r"--extra\s+([\w-]+)", line))
        for line in text.splitlines()
        if "uv sync" in line
    ]


def test_dockerfile_installs_every_runtime_extra():
    """The ⚠️ of plan PR 8, retired.

    Adding a seventh plugin with a new extra and forgetting the Dockerfile
    is now a red test instead of a silent production gap.
    """
    runtime = set(_extras()) - NON_RUNTIME_EXTRAS
    sync_lines = _uv_sync_extra_sets()
    assert sync_lines, "no `uv sync` line found in the Dockerfile — did it move?"
    for installed in sync_lines:
        assert installed == runtime, (
            f"Dockerfile installs {sorted(installed)} but pyproject declares "
            f"runtime extras {sorted(runtime)}"
        )


def test_every_uv_sync_is_frozen():
    """A build that re-resolves is a build whose image does not match the
    lock anyone reviewed."""
    text = re.sub(r"\\\s*\n\s*", " ", DOCKERFILE.read_text())
    for line in text.splitlines():
        if "uv sync" in line:
            assert "--frozen" in line, f"uv sync without --frozen: {line.strip()}"


def test_all_extra_is_the_union_of_the_runtime_extras():
    extras = _extras()
    runtime = set(extras) - NON_RUNTIME_EXTRAS
    referenced: set[str] = set()
    for spec in extras["all"]:
        for group in re.findall(r"\[([^\]]+)\]", spec):
            referenced |= {name.strip() for name in group.split(",")}
    assert referenced == runtime, (
        f"`all` covers {sorted(referenced)} but the runtime extras are {sorted(runtime)}"
    )


def test_dev_extra_pulls_in_all():
    """Both workflows run `uv sync --extra dev` and nothing else. Without
    this the CI environment would have no motor and ~200 tests would fail
    for a reason that has nothing to do with the change under test."""
    assert any("skkuverse-crawler[all]" in spec for spec in _extras()["dev"])


def test_optional_dependencies_are_not_also_base_dependencies():
    base = _base_dependency_names()
    for name in ("motor", "apscheduler", "tenacity", "pymongo"):
        assert name not in base, f"{name} is an extra — it must not be a base dependency"


def test_import_invisible_base_dependencies_are_present():
    """lxml is the trap of this PR: there is no `import lxml` anywhere, only
    `BeautifulSoup(raw, "lxml")`. Move it to an extra and every import,
    structure and isolation test stays green while production dies on the
    first page it parses. This assertion is the only cheap guard.

    click and python-dotenv are here for a different reason — they back the
    console script and env.py, so a core-only install needs them to produce
    a working binary at all.
    """
    base = _base_dependency_names()
    for name in ("lxml", "beautifulsoup4", "click", "python-dotenv", "httpx"):
        assert name in base, f"{name} must stay a base dependency"


def test_cli_extra_markers_match_the_declared_extras():
    """The CLI detects a missing extra by probing one distribution that the
    extra installs. Both halves drift independently — a renamed extra, or an
    extra whose contents change — so pin them to each other."""
    from skkuverse_crawler.cli import _EXTRA_MARKER, _LAZY

    extras = _extras()
    for extra, marker in _EXTRA_MARKER.items():
        assert extra in extras, f"_EXTRA_MARKER names {extra!r}, which pyproject does not declare"
        declared = {re.split(r"[><=!~\[]", spec)[0].strip().lower() for spec in extras[extra]}
        assert marker in declared, (
            f"probing {marker!r} for extra {extra!r}, but that extra installs {sorted(declared)}"
        )

    for name, (_module, _attr, _help, needed) in _LAZY.items():
        if needed is None:
            continue
        for extra in needed.split(","):
            assert extra.strip() in _EXTRA_MARKER, (
                f"command {name!r} requires extra {extra!r} with no marker to probe"
            )


def test_py_typed_marker_ships():
    """Hatch packages the whole src/skkuverse_crawler tree, so the marker
    needs no pyproject entry — but it does need to exist."""
    assert (PY_ROOT / "src" / "skkuverse_crawler" / "py.typed").is_file()
