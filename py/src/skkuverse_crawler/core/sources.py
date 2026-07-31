from __future__ import annotations


class SourceConfigError(RuntimeError):
    """sources.json could not be located, read, or validated.

    Raised instead of sys.exit(1) — library code must not kill the process
    (adr-006). One-shot CLIs exit non-zero via the uncaught exception; the
    scheduler logs it as a job error and stays alive.

    Lives in core/ ahead of the loader itself: core/sources.py is the
    loader's eventual home (PR 4+), so catchers never re-import the type.
    """
