"""Global test guards.

* Every test runs with a throwaway CBB_DATA_DIR and the SAFE default cost env.
* ALL outbound network is blocked at the socket layer for the whole test session.
  Any attempt to connect anywhere raises, and attempts are recorded so the
  zero-paid-request test can assert on them.
"""

from __future__ import annotations

import socket

import pytest

ATTEMPTS: list[tuple[str, object]] = []

SAFE_ENV = {
    "ALLOW_PAID_ODDS_API": "false",
    "ODDS_API_MAX_REQUESTS": "0",
    "ALLOW_CBBD": "false",
    "CBBD_MAX_REQUESTS": "0",
}


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("CBB_DATA_DIR", str(tmp_path / "data"))
    for k, v in SAFE_ENV.items():
        monkeypatch.setenv(k, v)
    for k in ("ODDS_API_KEY", "CBBD_API_KEY"):
        monkeypatch.delenv(k, raising=False)

    def guarded_connect(self, address, *a, **kw):
        ATTEMPTS.append(("connect", address))
        raise NetworkBlocked(f"network disabled in tests: {address!r}")

    def guarded_create_connection(address, *a, **kw):
        ATTEMPTS.append(("create_connection", address))
        raise NetworkBlocked(f"network disabled in tests: {address!r}")

    def guarded_getaddrinfo(host, *a, **kw):
        if host not in ("localhost", "127.0.0.1", "::1"):
            ATTEMPTS.append(("getaddrinfo", host))
            raise NetworkBlocked(f"DNS disabled in tests: {host!r}")
        return _real_getaddrinfo(host, *a, **kw)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    yield


_real_getaddrinfo = socket.getaddrinfo
