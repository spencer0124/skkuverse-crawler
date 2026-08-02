"""Structural boundary tests for the core/plugin split (adr-006).

Target-state tests that cannot pass yet are committed as
``xfail(strict=True)`` ratchets: the PR that enables one turns it into an
XPASS *failure*, forcing the marker's removal in that same diff. Reviewers
approve the target behavior here, in PR 0, not in the enabling PR.

**No ratchets remain.** The last one, `--help` importing motor, was retired
in PR 8; every test below is a permanent regression guard. Add a new ratchet
the same way if a future PR needs one.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

PY_ROOT = Path(__file__).parents[2]
SRC_PKG = PY_ROOT / "src" / "skkuverse_crawler"


def _run_python(code: str, *, empty_env: bool, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        env={} if empty_env else None,
        cwd=cwd or PY_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_help_does_not_import_optional_deps(tmp_path):
    """`--help` must not pay for infrastructure it will not use.

    Ratchet retired in PR 8: the CLI leaves now import shared.db inside
    function bodies, so nothing on the help path reaches motor. Widened
    beyond motor at the same time — pymongo/bson arrive independently
    (plugins/mongo/update_checker imports pymongo directly), and
    apscheduler/tenacity would regress the same way if a leaf grew an
    eager import.
    """
    code = (
        "import sys\n"
        "from click.testing import CliRunner\n"
        "from skkuverse_crawler.cli import main\n"
        "CliRunner().invoke(main, ['--help'])\n"
        "leaked = sorted(m for m in sys.modules if m.split('.')[0] in "
        "{'motor', 'pymongo', 'bson', 'apscheduler', 'tenacity'})\n"
        "print(','.join(leaked))\n"
        "sys.exit(1 if leaked else 0)\n"
    )
    result = _run_python(code, empty_env=False, cwd=tmp_path)
    assert result.returncode == 0, f"--help imported optional deps: {result.stdout.strip()}"


def test_core_import_is_infra_free(tmp_path):
    # Since PR 9 the bare package import carries most of this: core/__init__
    # re-exports every public submodule eagerly, so `import
    # skkuverse_crawler.core` executes them all. The three it deliberately
    # does NOT re-export (settings, registry, testing — see core/__init__'s
    # docstring) are still named explicitly, because nothing else would
    # reach them.
    code = (
        "import sys\n"
        "import skkuverse_crawler.core\n"
        "import skkuverse_crawler.core.registry\n"
        "import skkuverse_crawler.core.settings\n"
        "import skkuverse_crawler.core.testing\n"
        "sys.exit(1 if 'motor' in sys.modules or 'pymongo' in sys.modules else 0)\n"
    )
    result = _run_python(code, empty_env=False, cwd=tmp_path)
    assert result.returncode == 0, result.stderr


def test_core_import_stays_stdlib_only(tmp_path):
    """The eager re-export above is only safe while core has no third-party
    imports at all. httpx/bs4/lxml arriving here would be invisible to the
    motor/pymongo check yet would make `import skkuverse_crawler.core`
    quietly expensive — which is the property the re-export is trading on.
    """
    # core.testing is named explicitly: `import skkuverse_crawler.core` does
    # not reach it (deliberately not re-exported), and "stdlib only, and
    # pytest-free" is its own headline claim — a conformance suite that
    # needed pytest installed would be useless to the third parties it is
    # shipped for. pytest is in the leak set for exactly that reason.
    code = (
        "import sys\n"
        "import skkuverse_crawler.core\n"
        "import skkuverse_crawler.core.testing\n"
        "leaked = sorted(m for m in sys.modules if m.split('.')[0] in "
        "{'httpx', 'bs4', 'lxml', 'nh3', 'markdownify', 'imagesize', 'structlog', "
        "'click', 'dotenv', 'pytest'})\n"
        "print(','.join(leaked))\n"
        "sys.exit(1 if leaked else 0)\n"
    )
    result = _run_python(code, empty_env=False, cwd=tmp_path)
    assert result.returncode == 0, (
        f"importing skkuverse_crawler.core pulled in third-party packages: "
        f"{result.stdout.strip()}"
    )


def test_get_config_without_env_raises_typed_error(tmp_path):
    # cwd=tmp_path so load_dotenv() cannot find a real .env.
    code = (
        "from skkuverse_crawler.env import get_config\n"
        "try:\n"
        "    get_config()\n"
        "except SystemExit:\n"
        "    raise SystemExit(2)  # the lazy-init mine is still armed\n"
        "except Exception as exc:\n"
        "    raise SystemExit(0 if type(exc).__name__ == 'ConfigNotInitialized' else 3)\n"
        "raise SystemExit(4)  # produced a config out of thin air\n"
    )
    result = _run_python(code, empty_env=True, cwd=tmp_path)
    assert result.returncode == 0, (
        f"exit={result.returncode} (2=SystemExit mine, 3=wrong exception, "
        f"4=config from empty env) stderr={result.stderr[-300:]}"
    )


def test_health_logic_import_is_infra_free(tmp_path):
    """Permanent guard for the PR 2 cut: the health decision logic must
    import without motor/pymongo. Subprocess-only — the root conftest's
    _no_real_mongo fixture imports motor in-process for every test."""
    code = (
        "import sys\n"
        "import skkuverse_crawler.plugins.health.logic\n"
        "sys.exit(1 if ('motor' in sys.modules or 'pymongo' in sys.modules) else 0)\n"
    )
    result = _run_python(code, empty_env=False, cwd=tmp_path)
    assert result.returncode == 0, "importing plugins.health.logic pulled in motor/pymongo"


def test_whole_package_imports_with_empty_env(tmp_path):
    """Permanent guard: importing every module must never require env vars.

    Passes today (no module-level get_config() calls exist); any future
    import-time config read turns this red.
    """
    code = (
        "import importlib, pkgutil\n"
        "import skkuverse_crawler\n"
        "for mod in pkgutil.walk_packages(skkuverse_crawler.__path__, 'skkuverse_crawler.'):\n"
        "    if mod.name.endswith('__main__'):\n"
        "        continue  # importing __main__ RUNS the click CLI\n"
        "    importlib.import_module(mod.name)\n"
        "print('ok')\n"
    )
    result = _run_python(code, empty_env=True, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_env_is_the_only_environment_reader():
    """adr-006 결정 ①: `env.py` is the only file that touches os.environ.

    Stated in the architecture doc since v1 but never enforced — this is
    the guard. `os.environ`, `os.getenv` and `os.environ.get` all count.

    The allowlist has a second entry, and its presence is the honest
    record that the invariant as written was already false: the sources
    loader reads SOURCES_JSON_PATH directly, because path resolution runs
    before any Config exists (the container passes it as an env var, see
    PR 3). Routing it through env.py would mean initializing config to
    find the config file. Two readers, both named, is the real invariant.
    """
    # Exact paths, not a suffix match: `endswith("env.py")` would also
    # exempt dotenv.py, myenv.py, or plugins/anything/env.py.
    allowed = {"env.py", "modules/notices/config/loader.py"}
    readers = {"environ", "getenv"}
    violations = []

    for py_file in SRC_PKG.rglob("*.py"):
        rel = py_file.relative_to(SRC_PKG).as_posix()
        if rel in allowed:
            continue
        tree = ast.parse(py_file.read_text(), filename=str(py_file))

        # Track every name `os` is reachable under: `import os`, `import os
        # as _os`, and names bound by `from os import environ/getenv`.
        os_aliases = {"os"}
        direct_readers = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "os":
                        os_aliases.add(alias.asname or "os")
            elif isinstance(node, ast.ImportFrom) and node.module == "os":
                for alias in node.names:
                    if alias.name in readers:
                        direct_readers.add(alias.asname or alias.name)

        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                value = node.value
                if (
                    isinstance(value, ast.Name)
                    and value.id in os_aliases
                    and node.attr in readers
                ):
                    violations.append(f"{rel}:{node.lineno}: {value.id}.{node.attr}")
            elif isinstance(node, ast.Name) and node.id in direct_readers:
                violations.append(f"{rel}:{node.lineno}: bare {node.id} imported from os")

    assert not violations, (
        "only env.py may read the environment (adr-006 결정 ①):\n" + "\n".join(violations)
    )


def test_modules_do_not_import_plugins():
    """AST layering rule (adr-006 근거 ⑥): nothing under modules/ may import
    plugins. Trivially true today; becomes load-bearing at PR 4 when
    notices/ moves under modules/. Path-prefix rule — no hand-kept name list."""
    modules_dir = SRC_PKG / "modules"
    assert modules_dir.is_dir(), "modules/ package disappeared — update this test"
    violations = []
    for py_file in modules_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text(), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if "plugins" in name.split("."):
                    violations.append(f"{py_file.relative_to(PY_ROOT)}: {name}")
    assert not violations, "modules/ must not import plugins:\n" + "\n".join(violations)
