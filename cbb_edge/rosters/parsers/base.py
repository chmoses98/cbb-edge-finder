"""Shared roster-page parsing primitives (Wave 7).

Parsers return only what the page visibly states. A field the page does not show is
``None``; nothing is inferred and labelled as source-provided."""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field
from typing import Any

FIELDS = ("name", "jersey", "position", "height_in", "class_label", "hometown",
          "previous_school", "profile_url")  # fmt: skip
POSITIONS = re.compile(r"^(?:[GFC](?:/[GFC])?|PG|SG|SF|PF|G/F|F/C|GUARD|FORWARD|CENTER|"
                       r"POINT GUARD|SHOOTING GUARD|SMALL FORWARD|POWER FORWARD|WING|POST)$",
                       re.I)  # fmt: skip
CLASSES = re.compile(r"^(?:R-?|RS\.?\s*)?(?:FR|SO|JR|SR|GR|FRESHMAN|SOPHOMORE|JUNIOR|SENIOR|"
                     r"GRADUATE|GRAD|5TH|FIFTH|5TH YEAR|GRADUATE STUDENT)\.?$", re.I)  # fmt: skip


@dataclass
class ParsedRoster:
    platform: str
    players: list[dict[str, Any]] = field(default_factory=list)
    season_label: int | None = None


def txt(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def height_in(h: str | None) -> float | None:
    if not h:
        return None
    h = h.replace("’", "'").replace("”", '"').replace("″", '"').replace("′", "'")
    m = re.search(r"(\d)\s*(?:'|-|ft\.?)\s*(\d{1,2})", h)
    if not m:
        return None
    ft, inch = int(m.group(1)), int(m.group(2))
    return float(ft * 12 + inch) if 5 <= ft <= 7 and inch < 12 else None


def _season(text: str) -> int | None:
    for m in re.finditer(r"(20\d\d)\s*[-–/]\s*(\d\d)\b", text):
        if (int(m.group(1)) + 1) % 100 == int(m.group(2)):
            return int(m.group(1)) + 1
    return None


def season_label(page: str, url: str | None = None) -> int | None:
    """Target season the page itself states (2026-27 -> 2027), read ONLY from the
    <title>, the h1 / h2 headings, the selected option of a season selector, or a
    season in the URL path. Body text is never used: news links, archive menus and
    image paths carry other seasons. ``None`` when none of these shows a season."""
    for tag in ("title", "h1", "h2"):
        for m in re.findall(rf"<{tag}\b[^>]*>(.*?)</{tag}>", page, flags=re.S | re.I):
            s = _season(txt(m))
            if s:
                return s
    m = re.search(r'<body\b[^>]*class="[^"]*\broster-season-(20\d\d-\d\d)\b', page)
    if m:  # WMT page metadata
        return _season(m.group(1))
    for m in re.findall(r"<option\b[^>]*\bselected\b[^>]*>(.*?)</option>", page, flags=re.S | re.I):
        s = _season(txt(m))
        if s:
            return s
    if url:
        m = re.search(r"/(20\d\d)-(\d\d)(?:/|$)", url)
        if m:
            return _season(m.group(0))
    return None


def clean(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop rows without a plausible person name; de-duplicate on (name, jersey)."""
    out, seen = [], set()
    for p in players:
        nm = txt(p.get("name"))
        if not nm or len(nm) > 60 or len(nm.split()) < 2 or re.search(r"\d{3,}", nm):
            continue
        k = (nm.lower(), p.get("jersey"))
        if k in seen:
            continue
        seen.add(k)
        out.append({f: p.get(f) for f in FIELDS} | {"name": nm})
    return out
