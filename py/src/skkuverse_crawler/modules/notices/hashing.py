from __future__ import annotations

import hashlib


def compute_content_hash(clean_html: str | None) -> str | None:
    if not clean_html:
        return None
    return hashlib.sha256(clean_html.encode("utf-8")).hexdigest()
