"""The single network chokepoint. Every external request goes through :func:`fetch`.

Guarantees
----------
* ``cost_policy.authorize`` is called before every request (paid sources blocked).
* Responses are cached immutably under ``$CBB_DATA_DIR/bronze/<source>/...`` with a
  sidecar ``.meta.json`` (source, url, params, retrieved_at, sha256, bytes, schema).
  A cached response is returned without touching the network ("never pay twice").
* Per-source minimum request spacing and bounded exponential backoff on 429/5xx.
* Query parameters whose names look like secrets are never written to disk.

No other module may import ``requests``/``httpx``/``urllib.request`` (enforced by test).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from cbb_edge.data import cost_policy

SECRET_PARAM_HINTS = ("key", "token", "secret", "password", "auth")
USER_AGENT = "cbb-edge-finder/0.1 (research; contact via GitHub chmoses98/cbb-edge-finder)"

_last_request: dict[str, float] = {}
_spacing_lock = threading.Lock()


def data_dir() -> Path:
    return Path(os.environ.get("CBB_DATA_DIR", "data"))


def _redact(params: dict[str, Any] | None) -> dict[str, Any]:
    if not params:
        return {}
    return {
        k: ("<redacted>" if any(h in k.lower() for h in SECRET_PARAM_HINTS) else v)
        for k, v in sorted(params.items())
    }


def cache_key(source: str, url: str, params: dict[str, Any] | None) -> str:
    blob = json.dumps({"s": source, "u": url, "p": _redact(params)}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class FetchResult:
    path: Path
    meta: dict[str, Any]
    from_cache: bool

    def json(self) -> Any:
        return json.loads(self.path.read_text())


def _space(spec: cost_policy.SourceSpec) -> None:
    with _spacing_lock:
        last = _last_request.get(spec.key, 0.0)
        wait = spec.min_interval_s - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        _last_request[spec.key] = time.monotonic()


def fetch(
    source: str,
    url: str,
    params: dict[str, Any] | None = None,
    *,
    dest: str | Path | None = None,
    use_cache: bool = True,
    schema_version: str = "raw-v1",
    timeout: float = 120.0,
    max_attempts: int = 4,
    headers: dict[str, str] | None = None,
    session: requests.Session | None = None,
    not_found_ok: bool = False,
) -> FetchResult | None:
    """Fetch ``url`` for ``source`` through the cost policy, caching to bronze.

    ``dest`` is a path relative to ``$CBB_DATA_DIR/bronze/<source>/``; default is a
    content-addressed path from the request cache key. Returns ``None`` on 404 when
    ``not_found_ok`` (the 404 is also cached so it is never re-requested).
    """
    spec = cost_policy.SOURCES.get(source)
    if spec is None:
        raise cost_policy.CostPolicyViolation(f"Unregistered source {source!r}")
    key = cache_key(source, url, params)
    base = data_dir() / "bronze" / source
    path = base / (Path(dest) if dest else Path("_cache") / key[:2] / key)
    meta_path = path.with_name(path.name + ".meta.json")
    miss_path = path.with_name(path.name + ".404.json")
    if use_cache and path.exists() and meta_path.exists():
        return FetchResult(path, json.loads(meta_path.read_text()), True)
    if use_cache and not_found_ok and miss_path.exists():
        return None

    sess = session or requests.Session()
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    attempt = 0
    while True:
        attempt += 1
        # Authorize EVERY attempt (retries also consume paid quota).
        cost_policy.authorize(source, url)
        _space(spec)
        resp = sess.get(url, params=params, headers=hdrs, timeout=timeout, stream=True)
        if resp.status_code == 404 and not_found_ok:
            miss_path.parent.mkdir(parents=True, exist_ok=True)
            miss_path.write_text(
                json.dumps(
                    {
                        "url": url,
                        "params": _redact(params),
                        "status": 404,
                        "retrieved_at": datetime.now(UTC).isoformat(),
                    }
                )
            )
            return None
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_attempts:
            retry_after = resp.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2.0**attempt
            time.sleep(min(delay, 60.0))
            continue
        resp.raise_for_status()
        break

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".part-")
    with os.fdopen(fd, "wb") as fh:
        for chunk in resp.iter_content(1 << 20):
            fh.write(chunk)
    shutil.move(tmp, path)
    meta = {
        "source": source,
        "cost_class": str(spec.cost_class),
        "url": url,
        "params": _redact(params),
        "retrieved_at": datetime.now(UTC).isoformat(),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "schema_version": schema_version,
        "content_type": resp.headers.get("Content-Type"),
        "local_path": str(path.relative_to(data_dir())),
    }
    meta_path.write_text(json.dumps(meta, indent=1, sort_keys=True))
    return FetchResult(path, meta, False)
