import secrets

import pytest

from als.oracle import Oracle, classify
from als.store import Store
from conftest import network


def test_nonexistent_and_established_then_cached(store, transport):
    o = Oracle(store, transport=transport)
    absent = "als-absent-" + secrets.token_hex(8)
    r1 = o.resolve("pypi", absent)
    r2 = o.resolve("pypi", "requests")
    assert r1.bucket == "nonexistent" and not r1.exists
    assert r2.bucket == "established" and r2.exists
    calls = len(transport.calls)
    assert o.resolve("pypi", absent).from_cache
    assert o.resolve("pypi", "Requests").from_cache  # normalized key
    assert len(transport.calls) == calls, "second lookups must not hit the network"


def test_every_network_lookup_is_timestamped(store, transport):
    Oracle(store, transport=transport).resolve("pypi", "numpy")
    rows = store.db.execute("SELECT ts, url, status FROM lookups").fetchall()
    assert rows and all(r["ts"] for r in rows)
    assert store.get_oracle("pypi", "numpy")["checked_at"]


def test_buckets(store, transport):
    o = Oracle(store, transport=transport)
    assert o.resolve("pypi", "fresh-pkg").bucket == "young_or_obscure"
    assert o.resolve("pypi", "quiet-pkg").bucket == "young_or_obscure"
    assert o.resolve("pypi", "nofiles-pkg").bucket == "young_or_obscure"


def test_age_measured_at_check_time():
    b, _ = classify(True, "2026-01-01T00:00:00Z", 10_000, "2026-03-01T00:00:00+00:00", min_age_days=180)
    assert b == "young_or_obscure"
    b, _ = classify(True, "2026-01-01T00:00:00Z", 10_000, "2027-01-01T00:00:00+00:00", min_age_days=180)
    assert b == "established"


def test_lookup_error_not_cached(store):
    def broken(url):
        raise OSError("connection refused")
    o = Oracle(store, transport=broken, max_retries=0)
    r = o.resolve("pypi", "anything")
    assert r.bucket == "error"
    assert store.get_oracle("pypi", "anything") is None


def test_rate_limit_backoff(store, monkeypatch, transport):
    monkeypatch.setattr("als.oracle.time.sleep", lambda s: None)
    seq = iter([(429, b""), (429, b"")])

    def flaky(url):
        try:
            return next(seq)
        except StopIteration:
            return transport(url)
    assert Oracle(store, transport=flaky).resolve("pypi", "requests").bucket == "established"


@network
def test_live_registry(tmp_path):
    s = Store(tmp_path / "live.sqlite")
    o = Oracle(s)
    absent = "als-absent-" + secrets.token_hex(8)
    assert o.resolve("pypi", absent).bucket == "nonexistent"
    assert o.resolve("pypi", "requests").bucket == "established"
    n = o.network_calls
    o.resolve("pypi", absent)
    o.resolve("pypi", "requests")
    assert o.network_calls == n
    assert o.resolve("npm", "left-pad").exists
