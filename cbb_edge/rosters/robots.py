"""robots.txt for official sites (Wave 7): fetched once per host per run through the
chokepoint (cached), parsed with the standard library, consulted before every page.
A robots.txt that cannot be fetched (404) allows everything, as the convention says;
any other failure is treated as "disallow" (fail closed)."""

from __future__ import annotations

from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from cbb_edge.data.http import USER_AGENT, RedirectNotAuthorized, fetch

_cache: dict[str, RobotFileParser | None] = {}
redirects: dict[str, str] = {}  # host -> unregistered redirect target (not requested)


def _parser(source: str, scheme: str, host: str, stamp: str) -> RobotFileParser | None:
    key = f"{source}|{host}"
    if key in _cache:
        return _cache[key]
    rp: RobotFileParser | None = RobotFileParser()
    try:
        r = fetch(source, f"{scheme}://{host}/robots.txt", dest=f"robots/{stamp}/{host}.txt",
                  not_found_ok=True, timeout=30, max_attempts=2)  # fmt: skip
        assert rp is not None
        rp.parse([] if r is None else r.path.read_text(errors="replace").splitlines())
    except RedirectNotAuthorized as e:  # the site moved to a host not yet registered
        redirects[host] = e.target
        rp = None
    except Exception:  # noqa: BLE001  unreachable robots.txt -> fail closed
        rp = None
    _cache[key] = rp
    return rp


def allowed(source: str, url: str, stamp: str) -> bool:
    u = urlsplit(url)
    rp = _parser(source, u.scheme or "https", u.hostname or "", stamp)
    return rp is not None and rp.can_fetch(USER_AGENT, url)
