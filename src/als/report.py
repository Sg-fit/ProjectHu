"""`als report`: tables + figures to results/. One figure per claim."""

from __future__ import annotations

import json
from pathlib import Path

from . import metrics
from .store import Store, utcnow


def _pct(x) -> str:
    return "—" if x is None else f"{100 * x:.1f}%"


def _rate_table(title: str, groups: dict) -> list[str]:
    lines = [f"### {title}", "", "| group | runs | packages | hallucinated | prompt-level | package-level | squattable |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for g, r in groups.items():
        lines.append(f"| {g} | {r['runs']} | {r['packages']} | {r['hallucinated']} | {_pct(r['prompt_level_rate'])} | "
                     f"{_pct(r['package_level_rate'])} | {_pct(r['squattable_rate'])} |")
    return lines + [""]


def build(store: Store, prompts_meta: dict[str, dict], out_dir: str | Path) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    runs, pkgs = metrics.package_rows(store, prompts_meta)
    summary = {
        "generated_at": utcnow(),
        "db": store.path,
        "overall": metrics.rates(runs, pkgs),
        "recurrence": metrics.recurrence(pkgs),
        "by_model": metrics.breakdown(runs, pkgs, "model"),
        "by_framing": metrics.breakdown(runs, pkgs, "framing"),
        "by_obscurity": metrics.breakdown(runs, pkgs, "obscurity"),
        "by_ecosystem": metrics.breakdown(runs, pkgs, "ecosystem"),
        "by_domain": metrics.breakdown(runs, pkgs, "domain"),
        "shim": metrics.shim_metrics(store),
        "oracle_checked_range": [r for r in store.db.execute("SELECT MIN(checked_at), MAX(checked_at) FROM oracle").fetchone()],
        "spend_usd": store.total_cost(),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=list), encoding="utf-8")

    o, rec, shim = summary["overall"], summary["recurrence"], summary["shim"]
    md = [
        "# Results", "",
        f"Generated {summary['generated_at']} from `{store.path}`. Registry state as of "
        f"{summary['oracle_checked_range'][0]} – {summary['oracle_checked_range'][1]} (UTC). "
        "Claims about nonexistence are valid only as of those check times.", "",
        "## Headline", "",
        f"- Runs: **{o['runs']}**; resolved packages: **{o['packages']}** (unresolved imports excluded: {o['unresolved']})",
        f"- Prompt-level hallucination rate: **{_pct(o['prompt_level_rate'])}**",
        f"- Package-level hallucination rate: **{_pct(o['package_level_rate'])}**",
        f"- Squattable (exists, young or obscure): **{_pct(o['squattable_rate'])}**",
        f"- Distinct fake names: **{rec['distinct_fake_names']}** — R@2 {_pct(rec.get('R@2'))}, "
        f"R@3 {_pct(rec.get('R@3'))}, R@5 {_pct(rec.get('R@5'))}; seen across ≥2 models: {rec['cross_model_names']}",
        "",
        "## Recurring fake names — what a defender should pre-block", "",
        "Not a target list: every name below is blocked by the shim, and none was ever registered anywhere.", "",
        "| # | ecosystem | name | runs | prompts | models | framings |", "|---:|---|---|---:|---:|---|---|",
    ]
    for i, t in enumerate(rec["top20"], 1):
        md.append(f"| {i} | {t['ecosystem']} | `{t['name']}` | {t['runs']} | {t['prompts']} | {', '.join(t['models'])} | {', '.join(t['framings'])} |")
    md.append("")
    for title, key in (("By model", "by_model"), ("By framing", "by_framing"), ("By obscurity", "by_obscurity"),
                       ("By ecosystem", "by_ecosystem"), ("By domain", "by_domain")):
        md += _rate_table(title, summary[key])
    if shim:
        md += ["## Shim evaluation", "",
               f"Policy version(s): {', '.join(shim['policy_versions'])}. Cases: {shim['n']}", "",
               f"- Catch rate (blocked / hallucinated): **{_pct(shim['catch_rate'])}**",
               f"- False-positive rate (blocked or flagged / real control): **{_pct(shim['false_positive_rate'])}** "
               f"(hard blocks: {_pct(shim['false_positive_block_rate'])})",
               f"- Typo variants intercepted: {_pct(shim['typo_intercept_rate'])}; squattable names flagged: {_pct(shim['squattable_flag_rate'])}"]
        for mode, l in shim["latency_ms"].items():
            md.append(f"- Latency {mode}: p50 {l['p50']:.1f} ms, p95 {l['p95']:.1f} ms (n={l['n']})")
        if shim["false_positives"]:
            md += ["", "False positives (reported, not hidden):", ""]
            md += [f"- `{n}` → {v}: {r}" for n, v, r in shim["false_positives"]]
        md.append("")
    (out_dir / "report.md").write_text("\n".join(md), encoding="utf-8")
    _figures(summary, out_dir)
    return summary


def _figures(summary: dict, out_dir: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        (out_dir / "FIGURES_SKIPPED.txt").write_text("matplotlib not installed: pip install agentloop-sec[figures]\n")
        return
    rec = summary["recurrence"]
    ks = [k for k in ("R@2", "R@3", "R@5") if rec.get(k) is not None]
    if ks:
        fig, ax = plt.subplots(figsize=(4.5, 3))
        ax.bar(ks, [100 * rec[k] for k in ks], color="#4C6EF5")
        ax.set_ylabel("% of distinct fake names")
        ax.set_title("Fake names recur across independent runs")
        fig.tight_layout()
        fig.savefig(out_dir / "fig_recurrence.png", dpi=200)
        plt.close(fig)
    fr = summary["by_framing"]
    if fr:
        fig, ax = plt.subplots(figsize=(4.5, 3))
        keys = list(fr)
        ax.bar(keys, [100 * (fr[k]["prompt_level_rate"] or 0) for k in keys], color="#F08C00")
        ax.set_ylabel("% of runs with ≥1 fake package")
        ax.set_title("Hallucination rate by prompt framing")
        fig.tight_layout()
        fig.savefig(out_dir / "fig_framing.png", dpi=200)
        plt.close(fig)
