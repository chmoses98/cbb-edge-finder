"""Probe the public NCAA Membership Directory (Wave 7) from GitHub Actions.

Goal: find the structured public endpoints the directory's own web app calls, so the
D-I men's basketball universe and the official "Athletics Link" field can be read
without browser automation. Steps, all through the cost-policy chokepoint
(``ncaa_directory``, 2 s spacing):

1. robots.txt and the directory index page;
2. the app's script bundles, scanned for ``api/...`` endpoint strings;
3. a few candidate endpoints (reported, never assumed).

Raw responses go to ``samples/ncaa_directory/`` (committed to roster-source-samples).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

from cbb_edge.data.http import fetch

BASE = "https://web3.ncaa.org/directory/"
OUT = Path("samples/ncaa_directory")
CANDIDATES = [
    "api/common/conferenceList",
    "api/common/sportList",
    "api/directory/memberList?type=12&sportCode=MBB",
    "api/directory/memberList?type=12&division=I&sportCode=MBB",
    "api/directory/memberList?type=12",
]


def _get(url: str, name: str) -> tuple[str | None, dict]:
    try:
        r = fetch("ncaa_directory", url, use_cache=False, not_found_ok=True, timeout=45,
                  max_attempts=2, headers={"Accept": "application/json, text/html, */*"})  # fmt: skip
    except Exception as e:  # noqa: BLE001  report, never crash the probe
        return None, {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    if r is None:
        return None, {"status": 404}
    body = r.path.read_bytes()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_bytes(body)
    m = {k: r.meta.get(k) for k in ("bytes", "content_type", "last_modified", "etag")}
    (OUT / f"{name}.meta.json").write_text(json.dumps(r.meta, indent=1))
    return body.decode("utf-8", errors="replace"), m


def main() -> None:
    rep: dict = {}
    _, rep["robots"] = _get("https://web3.ncaa.org/robots.txt", "robots.txt")
    html, rep["index"] = _get(BASE, "index.html")
    scripts = re.findall(r'<script[^>]+src="([^"]+)"', html or "")
    rep["scripts"] = scripts
    endpoints: set[str] = set()
    for i, src in enumerate(scripts[:8]):
        js, m = _get(urljoin(BASE, src), f"bundle_{i}.js")
        rep[f"bundle_{i}"] = {"src": src, **m}
        for e in re.findall(r"""["'`]([^"'`\s]*api/[^"'`\s]{2,120})["'`]""", js or ""):
            endpoints.add(e)
    rep["endpoint_strings"] = sorted(endpoints)[:300]
    for i, c in enumerate(CANDIDATES):
        body, m = _get(urljoin(BASE, c), f"candidate_{i}.json")
        rep[f"candidate_{i}"] = {"path": c, **m, "head": (body or "")[:300]}
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
