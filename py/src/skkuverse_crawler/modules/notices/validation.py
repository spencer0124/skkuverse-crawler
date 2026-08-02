"""Pure validation predicates for stored notice data.

Two families, one home: attachment metadata checks and cleanMarkdown
rendering checks. Both are decisions about a notice's content, so they
belong to the notices module — the code that scans a database FOR them
lives in plugins/mongo/audit.py, and both the CLI and any library caller
can reach these directly.

``check_reachability`` is here too: it is HTTP, not storage, and the
module already owns HTTP content checks (image_verifier).
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from ...shared.logger import get_logger

logger = get_logger("notices_validation")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_HOST_SUFFIXES = ("skku.edu", "skkumed.ac.kr")
GNUBOARD_STRATEGIES = frozenset({"gnuboard", "gnuboard-custom"})

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AttachmentIssue:
    """A single validation problem on one attachment."""

    check: str  # e.g. "invalid_scheme", "blank_name", ...
    attachment_index: int
    detail: str
    url: str
    name: str


@dataclass
class NoticeValidationResult:
    """All issues found for one notice."""

    notice_id: str
    article_no: int
    source_id: str
    source_url: str
    issues: list[AttachmentIssue] = field(default_factory=list)


@dataclass
class ValidationReport:
    """Aggregated results across all scanned notices."""

    total_notices: int = 0
    total_attachments: int = 0
    notices_with_issues: int = 0
    issue_counts: dict[str, int] = field(default_factory=lambda: Counter())  # type: ignore[arg-type]
    results: list[NoticeValidationResult] = field(default_factory=list)
    skipped_http_checks: int = 0


# ---------------------------------------------------------------------------
# Sync validation functions (pure)
# ---------------------------------------------------------------------------


def validate_url_scheme(att: dict[str, str], index: int) -> AttachmentIssue | None:
    """URL must start with ``http://`` or ``https://``."""
    url = att.get("url", "")
    name = att.get("name", "")
    if not url or not url.strip():
        return AttachmentIssue("invalid_scheme", index, "empty URL", url, name)
    if url.strip() == "#":
        return AttachmentIssue("invalid_scheme", index, "anchor-only URL '#'", url, name)
    if not url.startswith(("http://", "https://")):
        return AttachmentIssue(
            "invalid_scheme", index, f"URL does not start with http(s)://: {url[:80]}", url, name,
        )
    return None


def validate_name(att: dict[str, str], index: int) -> AttachmentIssue | None:
    """Name must not be blank or ``'unknown'``."""
    url = att.get("url", "")
    name = att.get("name", "")
    if not name or not name.strip():
        return AttachmentIssue("blank_name", index, "empty attachment name", url, name)
    if name.strip().lower() == "unknown":
        return AttachmentIssue("blank_name", index, "name is 'unknown'", url, name)
    return None


def validate_name_is_url(att: dict[str, str], index: int) -> AttachmentIssue | None:
    """Flag when the name looks like a URL (lazy extraction)."""
    name = att.get("name", "")
    url = att.get("url", "")
    if name.startswith(("http://", "https://")):
        return AttachmentIssue("name_is_url", index, "name is a URL (likely extraction bug)", url, name)
    return None


def validate_referer(
    att: dict[str, str], index: int, strategy: str | None,
) -> AttachmentIssue | None:
    """Gnuboard/gnuboard-custom attachments must carry a ``referer``."""
    if strategy not in GNUBOARD_STRATEGIES:
        return None
    url = att.get("url", "")
    name = att.get("name", "")
    referer = att.get("referer", "")
    if not referer or not referer.strip():
        return AttachmentIssue(
            "missing_referer", index, "gnuboard attachment missing referer field", url, name,
        )
    return None


def validate_host_allowed(att: dict[str, str], index: int) -> AttachmentIssue | None:
    """Hostname must match the server proxy's ALLOWED_HOSTS."""
    url = att.get("url", "")
    name = att.get("name", "")
    if not url.startswith(("http://", "https://")):
        return None  # scheme check will flag this separately
    try:
        hostname = urlparse(url).hostname or ""
    except Exception:
        return AttachmentIssue("disallowed_host", index, f"malformed URL: {url[:80]}", url, name)
    if not any(hostname.endswith(suffix) for suffix in ALLOWED_HOST_SUFFIXES):
        return AttachmentIssue(
            "disallowed_host", index, f"host '{hostname}' not in allowed list", url, name,
        )
    return None


def validate_duplicates(attachments: list[dict[str, str]]) -> list[AttachmentIssue]:
    """Flag attachments that share the same URL within one notice."""
    seen: dict[str, int] = {}
    issues: list[AttachmentIssue] = []
    for i, att in enumerate(attachments):
        url = att.get("url", "")
        if not url:
            continue
        if url in seen:
            issues.append(AttachmentIssue(
                "duplicate_url", i,
                f"same URL as attachment[{seen[url]}]",
                url, att.get("name", ""),
            ))
        else:
            seen[url] = i
    return issues


def validate_notice_attachments(
    attachments: list[dict[str, str]],
    strategy: str | None = None,
) -> list[AttachmentIssue]:
    """Run all sync checks on one notice's attachments."""
    issues: list[AttachmentIssue] = []
    for i, att in enumerate(attachments):
        for check_fn in (_per_attachment_checks):
            issue = check_fn(att, i, strategy) if check_fn is validate_referer else check_fn(att, i)  # type: ignore[call-arg]
            if issue is not None:
                issues.append(issue)
    issues.extend(validate_duplicates(attachments))
    return issues


_per_attachment_checks = (
    validate_url_scheme,
    validate_name,
    validate_name_is_url,
    validate_referer,
    validate_host_allowed,
)

# ---------------------------------------------------------------------------
# Async HTTP reachability
# ---------------------------------------------------------------------------


async def check_reachability(
    url: str,
    referer: str,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    index: int,
    name: str,
) -> AttachmentIssue | None:
    """HEAD-request a single URL; return issue if unreachable."""
    async with semaphore:
        try:
            resp = await client.head(
                url,
                headers={"Referer": referer},
                follow_redirects=True,
            )
            if resp.status_code >= 400:
                return AttachmentIssue(
                    "unreachable", index,
                    f"HEAD returned {resp.status_code}",
                    url, name,
                )
        except httpx.TimeoutException:
            return AttachmentIssue("unreachable", index, "timeout", url, name)
        except httpx.HTTPError as exc:
            return AttachmentIssue("unreachable", index, f"HTTP error: {exc}", url, name)
        except Exception as exc:
            return AttachmentIssue("unreachable", index, f"unexpected error: {exc}", url, name)
    return None


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
