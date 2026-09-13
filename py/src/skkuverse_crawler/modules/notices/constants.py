SERVICE_START_DATE = "2026-03-09"

# ── View-counter refresh policy (adr-009) ────────────────────────────────
# A view counter moves on most page-0 notices within any 30-minute tick, so
# "write when it changed" barely reduces writes on its own: measured on prod
# 2026-09-13, ~809 of 1,455 touched documents would still write every tick.
# These two bounds turn a per-tick write into an occasional one.
#
# VIEWS_REFRESH_MIN_INTERVAL is the lever that does the work: a views-only
# write happens at most this often per document, so the whole collection
# costs ~(page-0 docs / 12) writes per tick instead of one each.
VIEWS_REFRESH_MIN_INTERVAL_HOURS = 6

# ...and the escape hatch, so a fast-moving notice is not stuck showing a
# stale number for six hours. The app renders the count at full precision
# (thousands separators only, no "1.2k" rounding), so the error IS visible —
# these bound it in relative terms rather than hiding it.
#
# The absolute floor matters most for a fresh notice: it is inserted with
# whatever count it had at first sight, often single digits, and 10% of a
# small number would fire on every tick and undo the interval.
VIEWS_REFRESH_MIN_DELTA = 50
VIEWS_REFRESH_MIN_RATIO = 0.10
