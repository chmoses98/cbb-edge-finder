"""Official roster discovery probe across the whole registry (Wave 7, from Actions).

Runs ``official.capture`` for every VERIFIED team (polite: per-host 5 s spacing,
robots.txt, <= 6 pages per site) and keeps raw evidence for parser development:
every fetched page of each team whose roster was not found / parsed thin, and the
roster page of the first three teams per platform. Gzipped into samples/official/.
Prints the discovery report.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

from cbb_edge.rosters import official

OUT = Path("samples/official")


def main() -> None:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    found = official.capture(2027, stamp)
    rep = official.discovery_report(found)
    OUT.mkdir(parents=True, exist_ok=True)
    per_platform: dict[str, int] = {}
    for d in found:
        keep = len(d.players) < 8
        if not keep and per_platform.get(d.platform, 0) < 3:
            per_platform[d.platform] = per_platform.get(d.platform, 0) + 1
            keep = True
        if not keep:
            continue
        team_dir = Path(d.page_path).parent if d.page_path else None
        from cbb_edge.data.http import data_dir

        base = data_dir() / "bronze" / "school_athletics" / "pages" / stamp / d.team_id
        for f in sorted((team_dir or base).glob("*.html"))[:4]:
            (OUT / f"{d.team_id}__{f.name}.gz").write_bytes(gzip.compress(f.read_bytes()))
    detail = [
        {"team_id": d.team_id, "base_url": d.base_url, "platform": d.platform,
         "roster_url": d.roster_url, "method": d.method, "n_players": len(d.players),
         "season_label": d.season_label, "requests": d.requests, "error": d.error,
         "redirect_to": d.redirect_to, "attempts": d.attempts}
        for d in found
    ]  # fmt: skip
    (OUT / "discovery_detail.json").write_text(json.dumps(detail, indent=1))
    print(json.dumps({k: v for k, v in rep.items() if k != "not_found"}, indent=1, default=str))


if __name__ == "__main__":
    main()
