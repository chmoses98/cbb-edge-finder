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


def season_label(page: str) -> int | None:
    """Target season from a visible heading/title such as "2026-27 Men's Basketball
    Roster" (returns 2027). ``None`` when the page shows no season."""
    t = _html.unescape(page)
    for pat in (r"(20\d\d)\s*[-–/]\s*(\d\d)\b[^<]{0,60}(?:roster|men'?s basketball)",
                r"(?:roster|men'?s basketball)[^<]{0,60}(20\d\d)\s*[-–/]\s*(\d\d)\b",
                r"/(20\d\d)-(\d\d)/roster"):  # fmt: skip
        m = re.search(pat, t, flags=re.I)
        if m and (int(m.group(1)) + 1) % 100 == int(m.group(2)):
            return int(m.group(1)) + 1
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
