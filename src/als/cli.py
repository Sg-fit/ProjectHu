"""`als` - the measurement harness.

  als run      [--models all|KEY,KEY] [--runs 5] [--limit N]   execute trials
  als score                                                   resolve extractions against the oracle
  als shim check NAME...                                      single-shot verdicts (same as als-shim check)
  als eval-shim                                               catch rate / FP / latency
  als report                                                  tables + figures to results/
  als reextract                                               re-run extractor over stored raw outputs
  als audit    [--n 50]                                       export a random extraction sample to hand-audit
  als label    NAME --label misattributed [--note ...]        record a hand label
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

import yaml

from .corpus import load_framings, load_prompts
from .oracle import Oracle
from .shim.policy import PROJECT_ROOT, load_policy
from .store import Store

DEFAULTS = {
    "db": PROJECT_ROOT / "results" / "als.sqlite",
    "models": PROJECT_ROOT / "config" / "models.yaml",
    "corpus": PROJECT_ROOT / "corpus" / "prompts.jsonl",
    "framings": PROJECT_ROOT / "corpus" / "framings.yaml",
    "control": PROJECT_ROOT / "corpus" / "control_packages.json",
    "results": PROJECT_ROOT / "results",
}


def _prompts_meta(path) -> dict[str, dict]:
    try:
        return {p.id: {"domain": p.domain, "obscurity": p.obscurity, "ecosystem": p.ecosystem, "task_id": p.task_id}
                for p in load_prompts(path)}
    except FileNotFoundError:
        return {}


def cmd_run(a) -> int:
    from .pipeline import BudgetExceeded, run_trials
    from .runners import make_runner

    cfg = yaml.safe_load(Path(a.models_cfg).read_text(encoding="utf-8"))
    entries = [m for m in cfg["models"] if m.get("enabled", True) and m["provider"] != "stub"]
    if a.models != "all":
        wanted = set(a.models.split(","))
        entries = [m for m in cfg["models"] if m["key"] in wanted]
    if not entries:
        print("no models selected", file=sys.stderr)
        return 2
    prompts = load_prompts(a.corpus)
    if a.limit:
        prompts = prompts[: a.limit]
    framings = load_framings(a.framings)
    store = Store(a.db)
    runners = [(m, make_runner(m)) for m in entries]
    runs = a.runs or cfg.get("defaults", {}).get("runs", 5)
    try:
        stats = run_trials(store, runners, prompts, framings, runs,
                           total_budget=(cfg.get("budget") or {}).get("total_usd"),
                           max_tokens=cfg.get("defaults", {}).get("max_tokens"))
    except BudgetExceeded as e:
        print(f"[run] stopped: {e}", file=sys.stderr)
        return 1
    print(f"[run] {stats}; total spend ${store.total_cost():.4f}", file=sys.stderr)
    return 0


def cmd_score(a) -> int:
    from .pipeline import score

    policy = load_policy(a.policy)
    store = Store(a.db)
    oracle = Oracle.from_policy(store, policy, refresh=a.refresh, fetch_downloads=not a.no_downloads)
    print(f"[score] {score(store, oracle, policy)}", file=sys.stderr)
    return 0


def cmd_shim(a) -> int:
    from .shim.cli import main as shim_main

    return shim_main(a.rest)


def cmd_eval_shim(a) -> int:
    from .shim.evaluate import evaluate, load_control, study_cases

    policy = load_policy(a.policy)
    store = Store(a.db)
    cases = load_control(a.control) + study_cases(store)
    n = evaluate(store, policy, cases, case_set="control+study")
    print(f"[eval-shim] {n} verdicts recorded under policy {policy['version']}", file=sys.stderr)
    return 0


def cmd_report(a) -> int:
    from .report import build

    s = build(Store(a.db), _prompts_meta(a.corpus), a.out)
    o = s["overall"]
    print(f"[report] {o['runs']} runs, {o['packages']} packages, {o['hallucinated']} hallucinated -> {a.out}/report.md",
          file=sys.stderr)
    return 0


def cmd_reextract(a) -> int:
    from .pipeline import reextract

    meta = _prompts_meta(a.corpus)
    n = reextract(Store(a.db), {k: v["ecosystem"] for k, v in meta.items()})
    print(f"[reextract] {n} runs re-extracted; re-run `als score`", file=sys.stderr)
    return 0


def cmd_audit(a) -> int:
    store = Store(a.db)
    rows = [dict(r) for r in store.db.execute(
        """SELECT x.id, r.model, r.prompt_id, x.ecosystem, x.name_raw, x.name_norm, x.surface_form, x.resolution,
                  x.context, o.bucket FROM extractions x JOIN runs r ON r.id=x.run_id
                  LEFT JOIN oracle o ON o.ecosystem=x.ecosystem AND o.name_norm=x.name_norm""")]
    random.Random(a.seed).shuffle(rows)
    sample = rows[: a.n]
    out = Path(a.out) / "audit_sample.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[*(sample[0].keys() if sample else ["id"]), "correct_extraction(y/n)", "misattributed(y/n)", "note"])
        w.writeheader()
        w.writerows(sample)
    print(f"[audit] {len(sample)} extractions -> {out} (seed {a.seed}). Fill in the last three columns by hand.", file=sys.stderr)
    return 0


def cmd_label(a) -> int:
    from .names import normalize

    Store(a.db).label(a.label, ecosystem=a.ecosystem, name_norm=normalize(a.name, a.ecosystem), note=a.note)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="als", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DEFAULTS["db"]))
    ap.add_argument("--corpus", default=str(DEFAULTS["corpus"]))
    ap.add_argument("--policy", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run")
    r.add_argument("--models", default="all")
    r.add_argument("--runs", type=int, default=None)
    r.add_argument("--limit", type=int, default=None, help="only the first N prompts (smoke test)")
    r.add_argument("--models-cfg", default=str(DEFAULTS["models"]))
    r.add_argument("--framings", default=str(DEFAULTS["framings"]))
    r.set_defaults(fn=cmd_run)

    s = sub.add_parser("score")
    s.add_argument("--refresh", action="store_true", help="ignore cache and re-check every name")
    s.add_argument("--no-downloads", action="store_true", help="skip download-count lookups")
    s.set_defaults(fn=cmd_score)

    sh = sub.add_parser("shim")
    sh.add_argument("rest", nargs=argparse.REMAINDER)
    sh.set_defaults(fn=cmd_shim)

    e = sub.add_parser("eval-shim")
    e.add_argument("--control", default=str(DEFAULTS["control"]))
    e.set_defaults(fn=cmd_eval_shim)

    rp = sub.add_parser("report")
    rp.add_argument("--out", default=str(DEFAULTS["results"]))
    rp.set_defaults(fn=cmd_report)

    rx = sub.add_parser("reextract")
    rx.set_defaults(fn=cmd_reextract)

    au = sub.add_parser("audit")
    au.add_argument("--n", type=int, default=50)
    au.add_argument("--seed", type=int, default=20261106)
    au.add_argument("--out", default=str(DEFAULTS["results"]))
    au.set_defaults(fn=cmd_audit)

    lb = sub.add_parser("label")
    lb.add_argument("name")
    lb.add_argument("--label", required=True, choices=["misattributed", "extractor_fp", "extractor_ok"])
    lb.add_argument("--ecosystem", default="pypi", choices=["pypi", "npm"])
    lb.add_argument("--note")
    lb.set_defaults(fn=cmd_label)
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
