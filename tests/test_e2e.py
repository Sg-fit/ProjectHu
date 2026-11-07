"""End-to-end on a 5-prompt corpus with a stubbed runner: populated DB + report, no manual steps."""

import json

from als.corpus import load_framings, load_prompts
from als.oracle import Oracle
from als.pipeline import run_trials, score
from als.report import build
from als.runners.stub import StubRunner
from als.shim.evaluate import evaluate, study_cases


def test_end_to_end(tmp_path, store, transport, policy):
    corpus = tmp_path / "prompts.jsonl"
    recs = [
        {"id": f"p{i}", "text": f"task {i}", "framing": f, "domain": "web", "ecosystem": "pypi",
         "obscurity": "niche" if i % 2 else "mainstream", "task_id": f"t{i}"}
        for i, f in enumerate(["f1", "f2", "f3", "f4", "f1"])
    ]
    corpus.write_text("\n".join(json.dumps(r) for r in recs))
    framings = tmp_path / "framings.yaml"
    framings.write_text("".join(f"{f}:\n  system: sys {f}\n" for f in ("f1", "f2", "f3", "f4")))

    canned = {
        "p0": "```bash\npip install requests\n```",
        "p1": "```bash\npip install requests fastjson-parse\n```",
        "p2": "Use the `fastjson-parse` library.\n```python\nimport numpy\nimport ghost_mod\n```",
        "p3": "```bash\npip install fresh-pkg asyncretry-helper\n```",
        "p4": "No libraries needed.",
    }
    runner = StubRunner({"key": "stub", "responses": canned})
    prompts = load_prompts(corpus)
    stats = run_trials(store, [({"key": "stub"}, runner)], prompts, load_framings(framings), runs=5)
    assert stats["done"] == 25
    # idempotent: re-running skips completed runs
    assert run_trials(store, [({"key": "stub"}, runner)], prompts, load_framings(framings), runs=5)["skipped"] == 25

    s = score(store, Oracle.from_policy(store, policy, transport=transport), policy)
    assert s["lookup_errors"] == 0 and s["verdicts"] > 0

    evaluate(store, policy, [("real", "pypi", "requests"), ("real", "pypi", "flask")] + study_cases(store),
             case_set="e2e", transport=transport)

    meta = {r["id"]: r for r in recs}
    summary = build(store, meta, tmp_path / "results")
    o, rec = summary["overall"], summary["recurrence"]
    assert o["runs"] == 25
    assert o["prompt_level_rate"] == 15 / 25           # p1, p2, p3 each in 5 runs
    assert o["unresolved"] == 5                         # ghost_mod: identity import, not counted
    assert rec["distinct_fake_names"] == 2
    assert rec["R@5"] == 1.0
    assert rec["top20"][0]["name"] == "fastjson-parse" and rec["top20"][0]["runs"] == 10
    assert summary["shim"]["catch_rate"] == 1.0
    assert summary["shim"]["false_positive_rate"] == 0.0
    assert (tmp_path / "results" / "report.md").read_text(encoding="utf-8").count("fastjson-parse") >= 1
