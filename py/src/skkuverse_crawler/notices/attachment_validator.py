"""
Validate attachment metadata stored in the notices collection.

Two layers:
1. **Sync checks** — pure functions that inspect attachment dicts for data
   integrity issues (bad URLs, blank names, missing referer, duplicates).
   No network or DB access.  Importable and testable in isolation.

2. **Async HTTP reachability** — HEAD requests to non-gnuboard attachment
   URLs.  Gnuboard URLs are skipped because they require a PHP session
   that only the server proxy manages.

Public API:
- ``validate_notice_attachments()`` — sync, per-notice check list
- ``validate_attachments()``        — async orchestrator (DB + HTTP)
- Result dataclasses for structured reporting
"""
from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from ..shared.logger import get_logger

logger = get_logger("attachment_validator")

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
    source_dept_id: str
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
# Top-level orchestrator
# ---------------------------------------------------------------------------


async def validate_attachments(
    *,
    dept_filter: tuple[str, ...] | None = None,
    limit: int | None = None,
    check_http: bool = True,
    http_concurrency: int = 20,
) -> ValidationReport:
    """Scan notices in MongoDB and validate their attachments.

    Parameters
    ----------
    dept_filter:
        Restrict to specific ``sourceDeptId`` values.
    limit:
        Max notices to scan.
    check_http:
        When True, perform HEAD requests on non-gnuboard URLs.
    http_concurrency:
        Max concurrent HTTP requests.
    """
    from ..shared.db import get_db
    from .config.loader import load_and_validate

    departments = load_and_validate()
    strategy_map: dict[str, str] = {
        dept["id"]: dept["strategy"] for dept in departments
    }

    db = await get_db()
    collection = db["notices"]

    query: dict = {"attachments": {"$exists": True, "$ne": []}}
    if dept_filter:
        query["sourceDeptId"] = {"$in": list(dept_filter)}

    report = ValidationReport()
    semaphore = asyncio.Semaphore(http_concurrency)

    client: httpx.AsyncClient | None = None
    if check_http:
        client = httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _BROWSER_UA})

    try:
        cursor = collection.find(query)
        if limit:
            cursor = cursor.limit(limit)

        count = 0
        async for doc in cursor:
            count += 1
            attachments: list[dict[str, str]] = doc.get("attachments", [])
            dept_id = doc.get("sourceDeptId", "")
            source_url = doc.get("sourceUrl", "")
            article_no = doc.get("articleNo", 0)
            notice_id = str(doc["_id"])

            strategy = strategy_map.get(dept_id)
            if strategy is None:
                logger.warning("unknown_dept", sourceDeptId=dept_id, notice_id=notice_id)

            report.total_notices += 1
            report.total_attachments += len(attachments)

            # Sync checks
            issues = validate_notice_attachments(attachments, strategy)

            # Async HTTP checks (non-gnuboard only)
            is_gnuboard = strategy in GNUBOARD_STRATEGIES
            if check_http and client is not None and not is_gnuboard:
                http_tasks = []
                for i, att in enumerate(attachments):
                    att_url = att.get("url", "")
                    if not att_url.startswith(("http://", "https://")):
                        continue  # scheme check already flagged
                    http_tasks.append(check_reachability(
                        att_url, source_url, client, semaphore, i, att.get("name", ""),
                    ))
                if http_tasks:
                    results = await asyncio.gather(*http_tasks, return_exceptions=True)
                    for r in results:
                        if isinstance(r, AttachmentIssue):
                            issues.append(r)
                        elif isinstance(r, Exception):
                            logger.warning("http_check_exception", error=str(r))
            elif is_gnuboard:
                report.skipped_http_checks += len(attachments)

            if issues:
                report.notices_with_issues += 1
                for issue in issues:
                    report.issue_counts[issue.check] += 1
                report.results.append(NoticeValidationResult(
                    notice_id=notice_id,
                    article_no=article_no,
                    source_dept_id=dept_id,
                    source_url=source_url,
                    issues=issues,
                ))

            if count % 200 == 0:
                logger.info("validation_progress", scanned=count)

    finally:
        if client is not None:
            await client.aclose()

    logger.info(
        "validation_complete",
        total=report.total_notices,
        issues=report.notices_with_issues,
    )
    return report
