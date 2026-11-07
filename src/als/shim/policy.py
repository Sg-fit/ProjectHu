"""Verdict logic. Reads policy.yaml; every verdict records the policy version."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from ..names import normalize
from ..oracle import OracleResult

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POLICY = PROJECT_ROOT / "config" / "policy.yaml"

ALLOW, FLAG, BLOCK = "allow", "flag", "block"


def load_policy(path: str | Path | None = None) -> dict:
    p = Path(path) if path else DEFAULT_POLICY
    with open(p, encoding="utf-8") as f:
        pol = yaml.safe_load(f)
    pol["_path"] = str(p)
    pol["_root"] = str(p.resolve().parent.parent)
    if "version" not in pol:
        raise ValueError(f"{p}: policy must declare a version")
    return pol


@lru_cache(maxsize=8)
def _load_top(path: str, top_n: int, ecosystem: str) -> tuple[str, ...]:
    p = Path(path)
    if not p.exists():
        return ()
    data = json.loads(p.read_text(encoding="utf-8"))
    names = data["packages"] if isinstance(data, dict) else data
    return tuple(normalize(n, ecosystem) for n in names[:top_n])


def top_packages(policy: dict, ecosystem: str) -> tuple[str, ...]:
    ts = policy.get("typosquat") or {}
    ref = (ts.get("reference") or {}).get(ecosystem)
    if not ref:
        return ()
    path = Path(ref)
    if not path.is_absolute():
        path = Path(policy.get("_root", PROJECT_ROOT)) / path
    return _load_top(str(path), int(ts.get("top_n", 1000)), ecosystem)


def within_distance_one(a: str, b: str) -> bool:
    """True iff Levenshtein(a, b) <= 1 (includes adjacent transposition, i.e. OSA distance 1)."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        diff = [i for i in range(la) if a[i] != b[i]]
        if len(diff) == 1:
            return True
        return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]
    if la > lb:
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def edit_distance(a: str, b: str, cap: int = 3) -> int:
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1]


def typosquat_target(name_norm: str, policy: dict, ecosystem: str) -> str | None:
    ts = policy.get("typosquat") or {}
    if not ts.get("enabled", False):
        return None
    top = top_packages(policy, ecosystem)
    if not top or name_norm in top:
        return None
    maxd = int(ts.get("max_distance", 1))
    for cand in top:
        if maxd == 1:
            if within_distance_one(name_norm, cand):
                return cand
        elif edit_distance(name_norm, cand, maxd) <= maxd:
            return cand
    return None


@dataclass
class Verdict:
    name: str
    ecosystem: str
    verdict: str
    reasons: list[str]
    bucket: str
    policy_version: str
    checked_at: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def decide(res: OracleResult, policy: dict) -> Verdict:
    v = str(policy["version"])
    meta = {k: getattr(res, k) for k in ("first_release", "last_release", "downloads_30d", "latest_version", "summary")}
    mk = lambda verdict, reasons: Verdict(res.name_norm, res.ecosystem, verdict, reasons, res.bucket, v, res.checked_at, meta)

    allow = {normalize(n, res.ecosystem) for n in policy.get("allowlist") or []}
    if res.name_norm in allow:
        return mk(ALLOW, ["on policy allowlist"])
    if res.bucket == "error":
        return mk(policy.get("on_lookup_error", FLAG), res.reasons or ["registry lookup failed"])
    if not res.exists:
        return mk(policy.get("nonexistent", BLOCK), [f"does not exist on {res.ecosystem} (checked {res.checked_at})"])

    reasons: list[str] = []
    target = typosquat_target(res.name_norm, policy, res.ecosystem)
    if target:
        reasons.append(f"one edit away from popular package '{target}'")
    reasons += [r for r in res.reasons]  # age / no-files / low-download reasons from the oracle
    if res.downloads_30d is None and policy.get("min_downloads") is not None and policy.get("unknown_downloads") == FLAG:
        reasons.append("download count unavailable")
    return mk(FLAG if reasons else ALLOW, reasons or ["established package"])
