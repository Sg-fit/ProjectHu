# agentloop-sec

Measuring and mitigating the **hallucination-to-action gap** in AI agent loops.

A hallucination is a correctness problem until the model's output is wired to an
actuator and executed before any human reads it. This project goes deep on one
pathway — **fabricated package references (P1)** — because it is the only one
whose ground truth is a free, objective, external lookup: a package name either
exists in a registry or it does not.

Two halves:

- **Measurement harness** — how often agent loops emit package names that don't
  exist, **whether the same fake names recur across independent runs** (the
  headline finding: a hallucination that recurs is squattable infrastructure),
  and which conditions make it worse.
- **Mitigation shim** — an interposer on the install path that resolves every
  proposed package name against the registry *before* execution and
  allows / flags / blocks it, measured for catch rate, false positives on real
  packages, and latency.

Package hallucination and "slopsquatting" are known and published; this project
does not claim first discovery. The contribution is the four-pathway,
actuator-centric taxonomy, **recurrence as the attack-surface metric**, and an
evaluated mitigation reported honestly with its costs.

## Install

```bash
python -m venv .venv && . .venv/Scripts/activate      # Windows; use bin/activate on POSIX
pip install -e ".[dev]"                                 # add [api] for the Anthropic runner, [figures] for plots
```

Reproducible installs with hashes:

```bash
pip install --require-hashes -r requirements-dev.lock
```

## Pipeline

```bash
als run      --models all --runs 5      # execute trials (budget-capped; see config/models.yaml)
als score                               # resolve every extracted name against the registry (cached)
als report                              # tables + figures -> results/
als eval-shim                           # shim catch rate / false positives / latency
als audit    --n 50                     # export a random extraction sample to hand-audit
```

The shim is also a standalone tool:

```bash
als-shim check requests fastjson-parse-helper   # verdicts, installs nothing
als-shim install flask some-package             # guarded pip install
als-shim exec -- pip install -r requirements.txt
```

Exit codes: `0` ok, `2` usage, `3` blocked, `4` needs human approval.

## How the shim decides

```
model -> proposed install command -> [ als-shim ] -> package manager -> environment
                                          |
                      registry lookup (deterministic; not a model)
                                          |
          nonexistent -> BLOCK    young/obscure -> FLAG    typosquat -> FLAG    established -> ALLOW
```

Thresholds live in `config/policy.yaml` and are **versioned** — every verdict
records the `policy_version` it was produced under, so tuned results stay
attributable. A deterministic external oracle is used on purpose: a second model
checking the first would inherit the failure mode being measured.

## Layout

```
config/      models.yaml (runners + budget), policy.yaml (versioned shim thresholds)
corpus/      prompts.jsonl (40 tasks x 4 framings), control_packages.json, top_pypi/npm reference lists
src/als/     corpus, runners/, extract, oracle, store, metrics, report, shim/
tests/       acceptance tests (offline by default; ALS_NETWORK_TESTS=1 hits live registries)
lab/         isolated-network attack demo (see lab/README.md)
results/     committed DB + figures, regenerable with one command
docs/        dev log
```

## Safety

- **Nothing is ever registered on a public registry.** The attack demo runs
  against a local index only (`lab/`).
- Benign marker payload only — writes one file, prints one line. No live malware.
- The demo's target container has no internet egress (`internal` Docker network).
- Prompts are synthetic; no personal data, no human subjects.
- **Dual-use:** the measurement half documents an attack surface; it is published
  alongside the mitigation, and the recurring-names table is framed as what
  defenders should pre-block. The defense is the point.

## Reproducibility

Every number in the writeup is regenerable from `results/als.sqlite`. Registry
lookups are timestamped (`lookups`, `oracle.checked_at`): a claim that a name
does not exist is valid only as of its check time.
