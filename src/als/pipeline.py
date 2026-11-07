"""`als run` and `als score`: execute trials, extract, resolve against the oracle."""

from __future__ import annotations

import sys
import traceback

from .corpus import Prompt
from .extract import extract
from .oracle import Oracle
from .runners.base import Runner
from .shim.policy import decide
from .store import Store


class BudgetExceeded(RuntimeError):
    pass


def run_trials(store: Store, runners: list[tuple[dict, Runner]], prompts: list[Prompt], framings: dict[str, str],
               runs: int, total_budget: float | None = None, max_tokens: int | None = None,
               log=lambda m: print(m, file=sys.stderr)) -> dict:
    stats = {"done": 0, "skipped": 0, "errors": 0}
    for cfg, runner in runners:
        model_budget = cfg.get("budget_usd")
        for p in prompts:
            for idx in range(runs):
                if store.has_run(cfg["key"], p.id, idx):
                    stats["skipped"] += 1
                    continue
                if total_budget is not None and total_budget > 0 and store.total_cost() >= total_budget:
                    raise BudgetExceeded(f"total budget ${total_budget:.2f} reached (spent ${store.total_cost():.2f})")
                if model_budget and store.total_cost(cfg["key"]) >= model_budget:
                    log(f"[run] {cfg['key']}: model budget ${model_budget:.2f} reached; skipping remaining")
                    break
                params = {"system": framings[p.framing], "run_idx": idx, "prompt_id": p.id,
                          "max_tokens": cfg.get("max_tokens") or max_tokens}
                try:
                    out = runner.complete(p.text, params)
                except Exception as e:  # recorded, retried on next `als run`
                    stats["errors"] += 1
                    store.add_run(model=cfg["key"], framing=p.framing, prompt_id=p.id, run_idx=idx,
                                  error=f"{type(e).__name__}: {e}", params_json={"traceback": traceback.format_exc()[-2000:]})
                    log(f"[run] {cfg['key']} {p.id}#{idx} ERROR {type(e).__name__}: {e}")
                    continue
                rid = store.add_run(model=cfg["key"], framing=p.framing, prompt_id=p.id, run_idx=idx,
                                    raw_output=out.text, params_json=out.params, served_model=out.served_model,
                                    stop_reason=out.stop_reason, input_tokens=out.input_tokens,
                                    output_tokens=out.output_tokens, cost_usd=out.cost_usd,
                                    latency_ms=out.latency_ms, error=None)
                store.replace_extractions(rid, extract(out.text, p.ecosystem))
                stats["done"] += 1
            else:
                continue
            break
        log(f"[run] {cfg['key']}: spent ${store.total_cost(cfg['key']):.4f}")
    return stats


def reextract(store: Store, ecosystem_of: dict[str, str]) -> int:
    """Re-run the extractor over every stored raw output (after an extractor fix)."""
    n = 0
    for r in store.db.execute("SELECT id, prompt_id, raw_output FROM runs WHERE error IS NULL").fetchall():
        store.replace_extractions(r["id"], extract(r["raw_output"] or "", ecosystem_of.get(r["prompt_id"], "pypi")))
        n += 1
    return n


def score(store: Store, oracle: Oracle, policy: dict, log=lambda m: print(m, file=sys.stderr)) -> dict:
    names = store.db.execute("SELECT DISTINCT ecosystem, name_norm FROM extractions ORDER BY ecosystem, name_norm").fetchall()
    resolved, errors = 0, 0
    results = {}
    for i, r in enumerate(names, 1):
        res = oracle.resolve(r["ecosystem"], r["name_norm"])
        results[(r["ecosystem"], r["name_norm"])] = res
        if res.bucket == "error":
            errors += 1
        resolved += 1
        if i % 50 == 0:
            log(f"[score] {i}/{len(names)} resolved ({oracle.network_calls} network calls)")
    version = str(policy["version"])
    rows = []
    for e in store.db.execute("SELECT id, ecosystem, name_norm FROM extractions").fetchall():
        res = results.get((e["ecosystem"], e["name_norm"]))
        if res is None:
            continue
        v = decide(res, policy)
        rows.append((e["id"], v.verdict, "; ".join(v.reasons), version))
    store.db.executemany("INSERT OR REPLACE INTO verdicts (extraction_id, verdict, reason, policy_version) VALUES (?,?,?,?)", rows)
    store.db.commit()
    return {"names": resolved, "lookup_errors": errors, "verdicts": len(rows), "network_calls": oracle.network_calls}
