# Frozen HTML fixtures for the characterization (golden) suite

These files are **frozen**: the goldens pin the crawler's byte-level output
for exactly this input. Editing a fixture invalidates every snapshot derived
from it — regenerate with `UPDATE_GOLDEN=1 pytest tests/characterization` and
re-review the snapshot diff by hand.

Rules (load-bearing):

- **No `<img>` tags in detail fixtures.** `_verify_and_measure_images`
  (orchestrator) issues a real HTTP request per image URL; the harness router
  fails loudly on any un-routed URL.
- **gnuboard dates use the full `YY-MM-DD` form** (e.g. `26-03-15`).
  `normalize_date` expands the short `MM-DD` form using `datetime.now()` —
  a golden built on it would flip at year boundaries.
- Regular-row dates are ≥ SERVICE_START_DATE (2026-03-09); the `floor_*`
  fixtures are deliberately below it.
- skku-standard pinned rows carry `공지` in the first info cell and repeat on
  every page in production; gnuboard's table parser never sets `pinned`, so
  pinned edge-case fixtures exist only under `skku_standard/`.
