"""
Validate cleanMarkdown fields stored in the notices collection.

Baseline static analysis: detects patterns that are either invalid CommonMark
(guaranteed rendering break) or valid CommonMark but historically problematic
in many renderers (suspicious, not confirmed break).

Severity interpretation:
- ``error``  — invalid CommonMark, will break in any renderer
- ``warning`` — valid CommonMark but suspicious, may break depending on renderer

Public API:
- ``validate_notice_markdown()`` — sync, per-notice check list
- ``validate_markdown()``        — async orchestrator (DB scan)
- Result dataclasses for structured reporting
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from ..shared.logger import get_logger

logger = get_logger("markdown_validator")

# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

_SEVERITY_RANK = {"error": 0, "warning": 1}


@dataclass(frozen=True)
class MarkdownIssue:
    """A single validation problem in one notice's markdown."""

    check: str  # e.g. "cross_line_strong", "broken_link"
    line: int  # 1-based line number
    detail: str
    snippet: str  # offending fragment (truncated)
    severity: str  # "error" | "warning"


@dataclass
class NoticeMarkdownResult:
    """All issues found for one notice."""

    notice_id: str
    article_no: int
    source_id: str
    source_url: str
    issues: list[MarkdownIssue] = field(default_factory=list)


@dataclass
class MarkdownValidationReport:
    """Aggregated results across all scanned notices."""

    total_notices: int = 0
    notices_with_issues: int = 0
    issue_counts: dict[str, int] = field(default_factory=lambda: Counter())  # type: ignore[arg-type]
    results: list[NoticeMarkdownResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_likely_opening_delimiter(md: str, pos: int) -> bool:
    """``**`` at *pos* is likely an opening delimiter (not closing).

    Heuristic based on CommonMark Rule 1: an opening ``**`` is typically
    preceded by whitespace or start-of-string.  If preceded by a content
    character (letter, digit, CJK), the ``**`` is almost certainly closing
    a preceding bold span.

    Note: this intentionally does NOT treat punctuation as "content" — a
    ``(**`` or ``-**`` could be a valid opening delimiter.  This means we
    may miss FPs like ``)**...** `` (paren before ``**``), but such cases
    are extremely rare in SKKU notice data and the trade-off favours fewer
    false negatives over perfect FP elimination.
    """
    if pos == 0:
        return True
    return md[pos - 1] in (" ", "\t", "\n")


def _line_of(md: str, pos: int) -> int:
    """Return 1-based line number for character position *pos*."""
    return md.count("\n", 0, pos) + 1


def _snippet(md: str, m: re.Match[str], max_len: int = 120) -> str:
    """Extract a truncated snippet from a regex match."""
    text = m.group()
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


# ---------------------------------------------------------------------------
# Sync check functions (pure)
# ---------------------------------------------------------------------------

# -- cross_line_strong -----------------------------------------------------
# Detect **text\ntext** where strong emphasis spans newlines.
# Valid CommonMark (soft break inside emphasis), but many renderers break on it.
#
# CommonMark delimiter rules applied to reduce false positives:
#   - Opening ** must be followed by non-whitespace (\S) — Rule 1
#   - Closing ** must be preceded by non-whitespace (\S) — Rule 12
# This eliminates the most common FP: closing ** on line N matched to
# opening ** on line N+1 (e.g. **A:** text\n\n**B:** text).
#
# Post-filter rejects matches whose captured groups contain ** to catch
# remaining edge cases like **A**\n**B**.

_CROSS_LINE_STRONG_RE = re.compile(
    r"\*\*"
    r"(\S(?:[^*\n]|\*(?!\*))*?)"  # must start with non-whitespace (opening rule)
    r"\n"
    r"((?:[^*]|\*(?!\*))*?\S)"  # must end with non-whitespace (closing rule)
    r"\*\*",
)


def check_cross_line_strong(md: str) -> list[MarkdownIssue]:
    """Strong emphasis spanning one or more newlines."""
    issues: list[MarkdownIssue] = []
    for m in _CROSS_LINE_STRONG_RE.finditer(md):
        pre, post = m.group(1), m.group(2)
        # Reject false positive: **A**\n**B** would capture "A**\n**B"
        if "**" in pre or "**" in post:
            continue
        # Reject false positive: closing ** matched as opening.
        if not _is_likely_opening_delimiter(md, m.start()):
            continue
        n_lines = m.group().count("\n")
        issues.append(MarkdownIssue(
            check="cross_line_strong",
            line=_line_of(md, m.start()),
            detail=f"Strong emphasis spans {n_lines} line(s)",
            snippet=_snippet(md, m),
            severity="warning",
        ))
    return issues


# -- space_before_close_emphasis -------------------------------------------
# Detect **text ** where a space precedes closing **.
# CommonMark Rule 12: right-flanking delimiter run must not be preceded by
# Unicode whitespace. This is guaranteed broken in every renderer.

_SPACE_BEFORE_CLOSE_STRONG_RE = re.compile(r"\*\*\S[^*\n]*[ \t]\*\*")


def check_space_before_close_emphasis(md: str) -> list[MarkdownIssue]:
    """Space or tab immediately before closing ``**``."""
    issues: list[MarkdownIssue] = []
    for m in _SPACE_BEFORE_CLOSE_STRONG_RE.finditer(md):
        # Reject false positive: closing ** matched as opening.
        # E.g. **이수자**로 **총 평점** — "**로 **" is NOT space-before-close.
        if not _is_likely_opening_delimiter(md, m.start()):
            continue
        issues.append(MarkdownIssue(
            check="space_before_close_emphasis",
            line=_line_of(md, m.start()),
            detail="Space before closing ** breaks bold in CommonMark",
            snippet=_snippet(md, m),
            severity="error",
        ))
    return issues


# -- empty_table_header ----------------------------------------------------
# Detect GFM tables where the header row has all-empty cells.
# | | | followed by | --- | --- | — content renders with a blank header row.

_EMPTY_TABLE_HEADER_RE = re.compile(
    r"^(\|[ \t]*)+\|[ \t]*\n"  # row of empty cells
    r"(\|[ \t]*-[-\s]*)+\|",  # separator row
    re.MULTILINE,
)


def check_empty_table_header(md: str) -> list[MarkdownIssue]:
    """GFM table with all-empty header cells."""
    issues: list[MarkdownIssue] = []
    for m in _EMPTY_TABLE_HEADER_RE.finditer(md):
        issues.append(MarkdownIssue(
            check="empty_table_header",
            line=_line_of(md, m.start()),
            detail="Table header row has all-empty cells",
            snippet=_snippet(md, m),
            severity="warning",
        ))
    return issues


# -- broken_link -----------------------------------------------------------
# Detect [text](url or ![alt](url where the closing paren is missing
# before end of line.

_BROKEN_LINK_RE = re.compile(
    r"!?\[[^\]]*\]\([^\)\n]*$",
    re.MULTILINE,
)


def check_broken_link(md: str) -> list[MarkdownIssue]:
    """Link or image with unclosed parenthesis."""
    issues: list[MarkdownIssue] = []
    for m in _BROKEN_LINK_RE.finditer(md):
        issues.append(MarkdownIssue(
            check="broken_link",
            line=_line_of(md, m.start()),
            detail="Unclosed parenthesis in link/image",
            snippet=_snippet(md, m),
            severity="error",
        ))
    return issues


# ---------------------------------------------------------------------------
# Per-notice orchestrator
# ---------------------------------------------------------------------------

_markdown_checks = (
    check_cross_line_strong,
    check_space_before_close_emphasis,
    check_empty_table_header,
    check_broken_link,
)


def validate_notice_markdown(
    md: str,
    *,
    min_severity: str = "warning",
) -> list[MarkdownIssue]:
    """Run all sync checks on one notice's cleanMarkdown.

    Parameters
    ----------
    md:
        The cleanMarkdown string to validate.
    min_severity:
        Minimum severity to include: ``"warning"`` (default, all) or
        ``"error"`` (errors only).
    """
    if not md or not md.strip():
        return []
    # Normalize CRLF (WYSIWYG/HWP sources may have Windows line endings)
    md = md.replace("\r\n", "\n")

    issues: list[MarkdownIssue] = []
    for check_fn in _markdown_checks:
        issues.extend(check_fn(md))

    if min_severity == "error":
        issues = [i for i in issues if i.severity == "error"]
    return issues


# ---------------------------------------------------------------------------
# Async DB orchestrator
# ---------------------------------------------------------------------------


async def validate_markdown(
    *,
    dept_filter: tuple[str, ...] | None = None,
    limit: int | None = None,
    min_severity: str = "warning",
) -> MarkdownValidationReport:
    """Scan notices in MongoDB and validate their cleanMarkdown fields.

    Parameters
    ----------
    dept_filter:
        Restrict to specific ``sourceId`` values.
    limit:
        Max notices to scan.
    min_severity:
        ``"warning"`` (default) or ``"error"``.
    """
    from ..shared.db import get_db

    db = await get_db()
    collection = db["notices"]

    query: dict = {"cleanMarkdown": {"$exists": True, "$ne": None}}
    if dept_filter:
        query["sourceId"] = {"$in": list(dept_filter)}

    report = MarkdownValidationReport()

    cursor = collection.find(
        query,
        {"cleanMarkdown": 1, "articleNo": 1, "sourceId": 1, "sourceUrl": 1},
    )
    if limit:
        cursor = cursor.limit(limit)

    count = 0
    async for doc in cursor:
        count += 1
        md = doc.get("cleanMarkdown", "")
        notice_id = str(doc["_id"])

        report.total_notices += 1

        issues = validate_notice_markdown(md, min_severity=min_severity)

        if issues:
            report.notices_with_issues += 1
            for issue in issues:
                report.issue_counts[issue.check] += 1
            report.results.append(NoticeMarkdownResult(
                notice_id=notice_id,
                article_no=doc.get("articleNo", 0),
                source_id=doc.get("sourceId", ""),
                source_url=doc.get("sourceUrl", ""),
                issues=issues,
            ))

        if count % 200 == 0:
            logger.info("validation_progress", scanned=count)

    logger.info(
        "validation_complete",
        total=report.total_notices,
        issues=report.notices_with_issues,
    )
    return report
