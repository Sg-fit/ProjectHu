"""`als eval-shim`: catch rate, false positives on the control set, added latency.

Case sets (truth labels):
  hallucinated - every distinct nonexistent name the study produced
  squattable   - every young_or_obscure name the study produced
  real         - control_packages.json real packages (never mixed into generation)
  typo         - control_packages.json typo variants of real packages

Each case is evaluated twice against a fresh, isolated cache: once cold
(network lookup) and once warm (cached), so latency is reported both ways.
The study's own oracle cache is never touched.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from ..metrics import package_rows
from ..oracle import Oracle
from ..store import Store, utcnow
from .policy import decide


def load_control(path: str | Path) -> list[tuple[str, str, str]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = []
    for p in data["real"]:
        cases.append(("real", p.get("ecosystem", "pypi"), p["name"]))
    for t in data.get("typo", []):
        cases.append(("typo", t.get("ecosystem", "pypi"), t["name"]))
    return cases


def study_cases(store: Store) -> list[tuple[str, str, str]]:
    _, pkgs = package_rows(store)
    seen, cases = set(), []
    for p in pkgs:
        truth = {"nonexistent": "hallucinated", "young_or_obscure": "squattable"}.get(p["bucket"])
        key = (p["ecosystem"], p["name"])
        if truth and key not in seen:
            seen.add(key)
            cases.append((truth, p["ecosystem"], p["name"]))
    return cases


def evaluate(store: Store, policy: dict, cases: list[tuple[str, str, str]], *, case_set: str = "default",
             transport=None, cache_path: str = ":memory:", log=lambda m: print(m, file=sys.stderr)) -> int:
    cache = Store(cache_path)
    oracle = Oracle.from_policy(cache, policy, transport=transport)
    version = str(policy["version"])
    rows = []
    for mode in ("cold", "warm"):
        for i, (truth, eco, name) in enumerate(cases, 1):
            t0 = time.perf_counter()
            v = decide(oracle.resolve(eco, name), policy)
            ms = (time.perf_counter() - t0) * 1000
            rows.append((case_set, name, eco, truth, v.verdict, "; ".join(v.reasons), ms, mode, version, utcnow()))
            if i % 50 == 0:
                log(f"[eval-shim] {mode} {i}/{len(cases)}")
    store.db.execute("DELETE FROM shim_eval WHERE case_set=? AND policy_version=?", (case_set, version))
    store.db.executemany(
        "INSERT INTO shim_eval (case_set, name, ecosystem, truth, verdict, reason, latency_ms, cache, policy_version, ts) VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    store.db.commit()
    cache.close()
    return len(rows)
