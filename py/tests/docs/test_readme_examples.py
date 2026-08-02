"""README code blocks are the example files, byte for byte.

A README example rots the moment the API moves, and nothing notices,
because a README is not executed. The fix is two-sided and needs both
halves: CI runs py/examples/*.py against a core-only install (so a broken
example fails the build), and this test asserts the README shows exactly
those files (so passing CI actually says something about what the reader
copies).

The link is an HTML comment above each fence:

    <!-- example: py/examples/quickstart.py -->
    ```python
    ...
    ```

HTML comments render as nothing on GitHub, and a fence info string of
plain `python` keeps syntax highlighting — the alternatives (```python
title=...) lose it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[3]
README = REPO_ROOT / "README.md"
EXAMPLES_DIR = REPO_ROOT / "py" / "examples"

# The comment marker, then a fenced block, with everything between them
# captured so a stray blank line or a prose paragraph in between fails
# rather than being skipped over.
BLOCK = re.compile(
    r"<!--\s*example:\s*(?P<path>\S+)\s*-->\n```python\n(?P<body>.*?)```\n",
    re.DOTALL,
)


def _blocks() -> list[tuple[str, str]]:
    return [(m.group("path"), m.group("body")) for m in BLOCK.finditer(README.read_text())]


def test_the_readme_has_example_blocks_at_all():
    """Guards the regex, not the content. A marker syntax change that
    matches nothing would make every test below vacuously pass."""
    assert len(_blocks()) >= 2, "no <!-- example: ... --> blocks found in README.md"


# ids from the paths only: pytest applies an `ids` callable to every
# element of the tuple, so the default would put the entire example source
# in the test name.
@pytest.mark.parametrize("path,body", _blocks(), ids=[p for p, _ in _blocks()])
def test_readme_block_matches_its_example_file(path: str, body: str):
    example = REPO_ROOT / path
    assert example.is_file(), f"README points at {path}, which does not exist"
    assert body == example.read_text(), (
        f"README's block for {path} has drifted from the file. The file is the "
        f"source — CI runs it — so copy the file into the README, not the other way."
    )


def test_every_example_file_appears_in_the_readme():
    """The other direction: an example CI runs but nobody is shown is an
    example nobody will keep working."""
    shown = {(REPO_ROOT / path).resolve() for path, _ in _blocks()}
    on_disk = {p.resolve() for p in EXAMPLES_DIR.glob("*.py")}
    missing = sorted(p.name for p in on_disk - shown)
    assert not missing, f"examples not shown in README.md: {missing}"


def test_examples_are_runnable_as_scripts():
    """CI invokes these with `python examples/<name>.py`, so each must do
    its own work at import time rather than define main() and stop."""
    for example in sorted(EXAMPLES_DIR.glob("*.py")):
        text = example.read_text()
        assert "asyncio.run(" in text, f"{example.name} defines work but never runs it"
