"""One fixture per verdict branch."""

from als.oracle import Oracle, OracleResult
from als.shim.policy import decide, within_distance_one


def _v(store, transport, policy, name):
    return decide(Oracle.from_policy(store, policy, transport=transport).resolve("pypi", name), policy)


def test_nonexistent_blocks(store, transport, policy):
    v = _v(store, transport, policy, "fastjson-parse")
    assert v.verdict == "block" and v.policy_version == "test"


def test_young_flags(store, transport, policy):
    v = _v(store, transport, policy, "fresh-pkg")
    assert v.verdict == "flag" and any("first release" in r for r in v.reasons)


def test_low_downloads_flags(store, transport, policy):
    v = _v(store, transport, policy, "quiet-pkg")
    assert v.verdict == "flag" and any("downloads" in r for r in v.reasons)


def test_typosquat_flags(store, transport, policy):
    v = _v(store, transport, policy, "reqests")
    assert v.verdict == "flag" and any("requests" in r for r in v.reasons)


def test_established_allows(store, transport, policy):
    assert _v(store, transport, policy, "flask").verdict == "allow"


def test_top_package_itself_not_typosquat(store, transport, policy):
    assert _v(store, transport, policy, "requests").verdict == "allow"


def test_allowlist(store, transport, policy):
    policy["allowlist"] = ["fastjson_parse"]
    assert _v(store, transport, policy, "fastjson-parse").verdict == "allow"


def test_lookup_error_fails_closed(policy):
    res = OracleResult("pypi", "x", "error", False, checked_at="t", reasons=["lookup failed: boom"])
    assert decide(res, policy).verdict == "flag"


def test_unknown_downloads_policy(store, policy):
    res = OracleResult("pypi", "solid", "established", True, first_release="2015-01-01T00:00:00Z", checked_at="2026-11-06T00:00:00+00:00")
    policy["unknown_downloads"] = "flag"
    assert decide(res, policy).verdict == "flag"
    policy["unknown_downloads"] = "allow"
    assert decide(res, policy).verdict == "allow"


def test_distance_one():
    assert within_distance_one("reqests", "requests")    # deletion
    assert within_distance_one("requestss", "requests")  # insertion
    assert within_distance_one("requezts", "requests")   # substitution
    assert within_distance_one("reqeusts", "requests")   # transposition
    assert not within_distance_one("rqeusts", "requests")
