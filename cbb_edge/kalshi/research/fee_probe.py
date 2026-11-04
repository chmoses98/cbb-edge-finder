"""Extract fee coefficients from the archived text of Kalshi's OFFICIAL fee schedule.

The development sandbox cannot reach kalshi.com, so a GitHub Actions workflow
(``fee-schedule-probe.yml``) downloads the official document, archives the raw bytes and the extracted
text immutably, and calls this module. Nothing here invents a coefficient: it only reports what the
text literally states, with the matching excerpts, and the research engine compares that with its
assumption. ``verified_official`` is True only when the text came from a kalshi.com URL AND a
quadratic ``coef x contracts x price x (1 - price)`` expression was found.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_TIMES = r"[x×*·]"
_C = r"(?:C|contracts?|number\s+of\s+contracts|N)"
_P = r"(?:P|price)"
_ONE_MINUS = r"\(\s*1\s*[-−–]\s*" + _P + r"\s*\)"
QUADRATIC = re.compile(
    rf"(?P<coef>\d*\.\d+)\s*{_TIMES}?\s*(?P<c>{_C})\s*{_TIMES}\s*{_P}\s*{_TIMES}\s*{_ONE_MINUS}",
    re.I,
)
QUADRATIC_ALT = re.compile(  # "0.07 * P * (1-P)" per contract (no explicit C)
    rf"(?<![\d.])(?P<coef>\d*\.\d+)\s*{_TIMES}\s*{_P}\s*{_TIMES}\s*{_ONE_MINUS}", re.I
)
ROUND_UP = re.compile(r"round(?:ed|ing)?\s+up|ceil(?:ing)?|next\s+(?:whole\s+)?cent", re.I)
EFFECTIVE = re.compile(
    r"(?:effective|updated|as\s+of)[^.\n]{0,40}?"
    r"([A-Z][a-z]{2,8}\.?\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})"
)
MULTIPLIER = re.compile(r"multiplier[^.\n]{0,60}?(\d*\.\d+|\d+)", re.I)


def parse_fee_text(text: str) -> dict[str, Any]:
    flat = re.sub(r"[ \t]+", " ", text.replace(" ", " "))
    taker: list[float] = []
    maker: list[float] = []
    excerpts: list[str] = []
    seen: set[tuple[int, float]] = set()
    for pat in (QUADRATIC, QUADRATIC_ALT):
        for m in pat.finditer(flat):
            coef = float(m.group("coef"))
            if not 0.0 < coef < 1.0 or (m.start(), coef) in seen:
                continue
            seen.add((m.start(), coef))
            ctx = flat[max(0, m.start() - 160) : m.end() + 40]
            is_maker = bool(re.search(r"maker", flat[max(0, m.start() - 160) : m.start()], re.I))
            (maker if is_maker else taker).append(coef)
            excerpts.append(" ".join(ctx.split())[:260])
    effective = [m.group(1) for m in EFFECTIVE.finditer(flat)][:5]
    return {
        "taker_coefficients": sorted(set(taker)),
        "maker_coefficients": sorted(set(maker)),
        "rounding_up_mentioned": bool(ROUND_UP.search(flat)),
        "effective_date_text": effective,
        "multiplier_mentions": [m.group(0)[:100] for m in MULTIPLIER.finditer(flat)][:5],
        "excerpts": excerpts[:12],
        "parse_status": "PARSED" if taker else "NO_QUADRATIC_EXPRESSION_FOUND",
    }


def build_evidence(
    text: str | None, *, source_url: str, sha256: str | None, error: str | None = None
) -> dict[str, Any]:
    host = (urlparse(source_url).hostname or "").lower()
    official = host == "kalshi.com" or host.endswith(".kalshi.com")
    parsed = parse_fee_text(text) if text else {"parse_status": "NO_TEXT"}
    verified = bool(
        official and not error and parsed["parse_status"] == "PARSED"
    )  # literal formula found in text served by kalshi.com
    return {
        "schema_version": "fee-evidence-v1",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "source_url": source_url,
        "source_is_official_host": official,
        "document_sha256": sha256,
        "fetch_error": error,
        "verified_official": verified,
        "status": "VERIFIED_OFFICIAL" if verified else ("FETCH_FAILED" if error else "UNVERIFIED"),
        **parsed,
    }


def compare_with_assumption(
    evidence: dict[str, Any] | None, taker: float, maker: float
) -> dict[str, Any]:
    """Status of our coefficients against the official text (never silently adopted)."""
    if not evidence or not evidence.get("verified_official"):
        return {"status": "UNVERIFIED", "assumed_taker": taker, "assumed_maker": maker,
                "reason": (evidence or {}).get("status", "no_evidence_archived")}  # fmt: skip
    ot = evidence.get("taker_coefficients") or []
    om = evidence.get("maker_coefficients") or []
    ok_t = any(abs(c - taker) < 1e-9 for c in ot)
    ok_m = (not om) or any(abs(c - maker) < 1e-9 for c in om)
    return {
        "status": "MATCH" if ok_t and ok_m else "MISMATCH",
        "assumed_taker": taker, "assumed_maker": maker,
        "official_taker": ot, "official_maker": om,
        "taker_match": ok_t, "maker_match": ok_m,
        "effective_date_text": evidence.get("effective_date_text"),
        "document_sha256": evidence.get("document_sha256"),
        "retrieved_at": evidence.get("retrieved_at"),
    }  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--text", type=Path, help="extracted text of the fee document")
    ap.add_argument("--raw", type=Path, help="raw downloaded bytes (for the sha256)")
    ap.add_argument("--source-url", required=True)
    ap.add_argument("--error", default=None)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    text = a.text.read_text(errors="replace") if a.text and a.text.exists() else None
    sha = hashlib.sha256(a.raw.read_bytes()).hexdigest() if a.raw and a.raw.exists() else None
    ev = build_evidence(text, source_url=a.source_url, sha256=sha, error=a.error)
    a.out.write_text(json.dumps(ev, indent=1, sort_keys=True))
    print(json.dumps({k: ev[k] for k in ("status", "taker_coefficients", "maker_coefficients")}
                     if "taker_coefficients" in ev else {"status": ev["status"]}))  # fmt: skip


if __name__ == "__main__":
    main()
