# Dev log

Dated, append-only. Feeds the Process & Learning section (15 pts) and is part of
the originality evidence (continuous git history). Convert any relative dates to
absolute.

## 2026-11-06 — Day 1: scaffold, core, acceptance tests

**Planned (week 1 of the build spec):** register for the Challenge (not a build
task — do first), lock the taxonomy, corpus to 120+, harness skeleton + oracle +
acceptance tests passing.

**Built today, in order:**
- Repo contract from the spec: `config/`, `corpus/`, `src/als/…`, `tests/`, `lab/`,
  `results/`. Minimal runtime deps (PyYAML only) — a tool that defends the install
  path should not drag in a deep dependency tree; noted that this is thematically
  apt for the writeup.
- `names.py` + `extract.py` first, because the spec flags the extractor as the
  piece most likely to silently wreck the numbers. Handles pip/uv/poetry/npm
  install commands, requirements blocks, pyproject/package.json manifests, Python
  and JS imports, and ticked prose mentions. Import→distribution alias table
  (`cv2`→`opencv-python`, etc.); unmapped imports are recorded as `identity` and
  never counted as hallucinated on their own — they bucket `unresolved`.
- `oracle.py`: PyPI/npm existence + metadata, four buckets (nonexistent /
  young_or_obscure / established / misattributed), cached in SQLite, every lookup
  timestamped. Age is measured at *check time* so cached results reclassify
  identically on re-runs.
- `store.py`: schema per the spec (runs, extractions, oracle, verdicts,
  shim_eval) plus `lookups` (timestamp evidence) and `labels` (hand labels).
- `shim/`: `policy.py` (versioned verdicts, OSA edit-distance typosquat check),
  `interpose.py` (pre-execution guard with an explicit, actionable agent
  message), `cli.py` (`als-shim check|install|exec`).
- Runners: Anthropic API (`claude-opus-5-5`, effort recorded since sampling knobs
  are rejected; refusal fallbacks OFF so the answering model is never swapped
  silently), Ollama local, deterministic stub.
- `pipeline.py` (run/score/reextract), `metrics.py` (all rates incl. R@k and
  top-20 recurring), `report.py`, `shim/evaluate.py`, `als` CLI.

**Acceptance tests (written alongside, passing):** 34 pass offline, 1 live test
passes against real PyPI/npm. Extractor recovers every planted name across all
surface forms with zero false positives on plain prose; normalization collapses
`Foo_Bar`/`foo-bar`/`foo.bar`; oracle caches and the second lookup makes no
network call; one policy fixture per verdict branch; end-to-end on a 5-prompt
stub corpus produces a populated DB + report with no manual steps.

**Corpus:** 40 tasks across web/data/crypto/embedded/media/networking/ml, each in
4 framings (f1 bare, f2 "well-maintained library", f3 presupposes an unnamed
standard helper, f4 agentic/commands-run-unreviewed) = 160 prompts. f3/f4 are the
ones expected to matter. Control set: 115 real packages stratified by popularity
rank + 50 deterministic typo variants, kept entirely separate from the generation
corpus. Top-PyPI reference list (15,000 names, pinned snapshot dated 2026-11-01)
drives the typosquat check.

**First real numbers (shim, control set only — no model runs yet):**
- Typo variants intercepted: 100% (50/50).
- False-positive rate on real packages: 0.9% — a single flag,
  `pyside6-webengine`, legitimately young (first release 31 days before check,
  0 recent downloads via pypistats). Reported, not hidden; it is a *flag* (human
  approval), not a hard block. Hard-block FP rate: 0.0%.
- Lookup latency: p50 ~358 ms cold, ~0 ms warm (cache).

**Decisions / corrections:**
- `uv pip install` surface form initially mislabeled `uv_add`; fixed to
  `pip_install` (the first acceptance-test failure — kept the test).
- Added a configurable `ALS_PYPI_BASE` to the oracle so the lab can point it at
  the local index without code changes, and so the shim can check a name against
  *public* PyPI even inside the air-gapped demo.
- Safety boundary in practice: did not script creation of the install-time demo
  payload. The lab is designed so "publishing" to the local index is a manual
  copy step; `lab/demo/README.md` documents the benign marker procedure instead.
  This matches the "benign payload only, nothing ever public" hard rule and
  strengthens the Safety section.

**Open / next (week 1 remainder, then week 2):**
- Register for the Challenge; attend the Nov 12 webinar (4 PM ET).
- **Originality question** (spec §8) for Monday office hours / SI.Challenge@doe.gov:
  does a project also entered in a science fair satisfy "created specifically for
  the Challenge"? Get it in writing before week 3.
- Full measurement run across models; recurrence analysis; hand-audit 50
  extractions (`als audit --n 50`) for extractor accuracy — do not skip.
