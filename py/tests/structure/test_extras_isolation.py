"""Extras isolation: no module outside the adapter layer may need an extra.

``test_whole_package_imports_with_empty_env`` cannot prove this. It runs in
the dev environment, where every extra IS installed, so an accidental
``import motor`` under modules/ is invisible to it. This file poisons the
optional distributions in a subprocess and imports everything again, which
makes the violation observable without building a venv.

What it proves: import-graph isolation — core/, modules/ and shared/ (minus
the adapters below) import cleanly with the optional distributions absent.

What it does NOT prove: that the *packaging* is right. A dependency that is
never imported cannot be caught here — lxml is used only as a parser NAME
string, so moving it into an extra would keep this test green and fail at
crawl time. That class of bug is covered by test_packaging.py's positive
base-dependency assertion and by the clean-venv CI job.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PY_ROOT = Path(__file__).parents[2]

# Distributions installed only by an extra (plus what they drag in).
POISONED = ("motor", "pymongo", "bson", "apscheduler", "tenacity", "dnspython")

# Modules allowed to need an extra, each for a stated reason.
ADAPTERS = (
    "skkuverse_crawler.plugins",   # a plugin needing its own extra is the design
    "skkuverse_crawler.wiring",    # composition root — imports plugins by definition
    "skkuverse_crawler.shared.db", # a mongo adapter that has not moved yet (shared/ dissolution)
    "skkuverse_crawler.__main__",  # importing it RUNS the CLI
)

_PROBE = f"""
import importlib, pkgutil, sys

POISONED = {POISONED!r}
ADAPTERS = {ADAPTERS!r}


class _Poison:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in POISONED:
            raise ModuleNotFoundError(f"No module named {{name!r}} (poisoned: optional dep)")
        return None


sys.meta_path.insert(0, _Poison())

import skkuverse_crawler

violations = []
for mod in pkgutil.walk_packages(skkuverse_crawler.__path__, "skkuverse_crawler."):
    if mod.name.startswith(ADAPTERS):
        continue
    try:
        importlib.import_module(mod.name)
    except ModuleNotFoundError as exc:
        violations.append(f"{{mod.name}}: {{exc}}")

print("\\n".join(violations))
sys.exit(1 if violations else 0)
"""


def test_no_module_outside_the_adapter_layer_needs_an_extra():
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=PY_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        "these modules cannot be imported without an optional dependency "
        f"installed:\n{result.stdout.strip()}\n{result.stderr.strip()}"
    )


def test_the_poison_hook_actually_bites():
    """Guard the guard: if the hook silently stopped working, the test
    above would pass for the wrong reason and never fail again."""
    code = _PROBE.replace(
        'import skkuverse_crawler\n', 'import skkuverse_crawler\nimport motor\n', 1
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=PY_ROOT, capture_output=True, text=True, timeout=120
    )
    assert result.returncode != 0
    assert "poisoned" in result.stderr
