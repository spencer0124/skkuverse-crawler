from __future__ import annotations

from bs4 import BeautifulSoup, Tag


def load_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def extract_text(tag: Tag | None) -> str:
    if tag is None:
        return ""
    return tag.get_text(strip=True)


def extract_attr(tag: Tag | None, attr: str) -> str | None:
    if tag is None:
        return None
    val = tag.get(attr)
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, list):
        return " ".join(val).strip()
    return None
