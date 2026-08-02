"""The package top level: one nice import, and it must stay cheap.

`from skkuverse_crawler import iter_notices` is the first line of the
README, so it has to work. The interesting half is the other direction —
that having it does not make every other import expensive.
"""

from __future__ import annotations

import pytest

from .test_boundaries import _run_python


def test_the_facade_is_importable_from_the_top_level():
    import skkuverse_crawler
    from skkuverse_crawler.modules.notices.simple import iter_notices as direct

    assert skkuverse_crawler.iter_notices is direct


def test_version_is_exposed_and_matches_the_installed_distribution():
    from importlib.metadata import version

    import skkuverse_crawler

    assert skkuverse_crawler.__version__ == version("skkuverse-crawler")


def test_dir_lists_the_lazy_names():
    """Module __getattr__ is invisible to the default __dir__, so without
    an explicit __dir__ neither name shows up in tab completion."""
    import skkuverse_crawler

    assert set(skkuverse_crawler.__all__) <= set(dir(skkuverse_crawler))


def test_an_unknown_attribute_still_raises_attribute_error():
    """A __getattr__ that returns None or raises the wrong type breaks
    hasattr(), inspect and every `try: from x import y` guard."""
    import skkuverse_crawler

    with pytest.raises(AttributeError):
        skkuverse_crawler.no_such_thing


def test_importing_a_core_submodule_stays_cheap(tmp_path):
    """The reason the top-level re-export is lazy.

    Importing any submodule executes the package __init__ first. An eager
    `from .modules.notices.simple import iter_notices` there would pull
    the strategies — and therefore bs4, lxml and httpx — into every
    `import skkuverse_crawler.core.ports`. The infra-free tests only watch
    motor/pymongo, so they would stay green while core stopped being cheap
    to import. This is the alarm for that.
    """
    code = (
        "import sys\n"
        "import skkuverse_crawler.core.ports\n"
        "leaked = sorted(m for m in sys.modules if m.split('.')[0] in "
        "{'bs4', 'lxml', 'httpx', 'markdownify', 'nh3', 'imagesize'})\n"
        "print(','.join(leaked))\n"
        "sys.exit(1 if leaked else 0)\n"
    )
    result = _run_python(code, empty_env=False, cwd=tmp_path)
    assert result.returncode == 0, (
        f"the top-level __init__ stopped being lazy — importing core.ports "
        f"pulled in: {result.stdout.strip()}"
    )


def test_the_top_level_import_itself_pulls_in_nothing(tmp_path):
    """`import skkuverse_crawler` on its own must touch no submodule.
    Anything that changes this (a convenience re-export, a version check
    at import time) also changes the cost of every import above."""
    code = (
        "import sys\n"
        "import skkuverse_crawler\n"
        "submodules = sorted(m for m in sys.modules "
        "if m.startswith('skkuverse_crawler.'))\n"
        "print(','.join(submodules))\n"
        "sys.exit(1 if submodules else 0)\n"
    )
    result = _run_python(code, empty_env=False, cwd=tmp_path)
    assert result.returncode == 0, (
        f"importing the package eagerly loaded: {result.stdout.strip()}"
    )
