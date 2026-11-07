"""Shared fixtures: an offline fake registry so tests never touch the network."""

import json
import os

import pytest

from als.store import Store

# name -> (first_release ISO, downloads_30d); anything absent is a 404.
FAKE_PYPI = {
    "requests": ("2011-02-14T00:00:00Z", 900_000_000),
    "numpy": ("2006-12-02T00:00:00Z", 400_000_000),
    "flask": ("2010-04-16T00:00:00Z", 90_000_000),
    "fresh-pkg": ("2026-10-30T00:00:00Z", 50_000),       # young
    "quiet-pkg": ("2019-01-01T00:00:00Z", 12),           # obscure
    "reqests": ("2018-01-01T00:00:00Z", 50_000),         # typo of requests, old + downloaded
    "nofiles-pkg": (None, 0),
}


class FakeTransport:
    def __init__(self, pypi=None):
        self.pypi = FAKE_PYPI if pypi is None else pypi
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if url.startswith("https://pypi.org/pypi/"):
            name = url.split("/pypi/")[1].split("/json")[0]
            if name not in self.pypi:
                return 404, b'{"message": "Not Found"}'
            first, _ = self.pypi[name]
            releases = {"1.0": [{"upload_time_iso_8601": first}]} if first else {"1.0": []}
            return 200, json.dumps({"info": {"version": "1.0", "summary": f"{name} summary"}, "releases": releases}).encode()
        if url.startswith("https://pypistats.org/api/packages/"):
            name = url.split("/packages/")[1].split("/recent")[0]
            if name not in self.pypi:
                return 404, b""
            return 200, json.dumps({"data": {"last_day": 1, "last_week": 1, "last_month": self.pypi[name][1]}}).encode()
        if url.startswith("https://registry.npmjs.org/"):
            return 404, b"{}"
        if url.startswith("https://api.npmjs.org/"):
            return 404, b"{}"
        raise AssertionError(f"unexpected URL {url}")


@pytest.fixture
def transport():
    return FakeTransport()


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.sqlite")
    yield s
    s.close()


@pytest.fixture
def policy(tmp_path):
    from als.shim.policy import load_policy

    pol = load_policy()
    top = tmp_path / "top_pypi.json"
    top.write_text(json.dumps({"packages": ["requests", "numpy", "flask", "boto3", "urllib3"]}))
    pol["typosquat"] = {"enabled": True, "max_distance": 1, "top_n": 1000, "reference": {"pypi": str(top)}}
    pol["version"] = "test"
    return pol


network = pytest.mark.skipif(os.environ.get("ALS_NETWORK_TESTS") != "1", reason="set ALS_NETWORK_TESTS=1")
