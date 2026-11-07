# Results

Generated 2026-11-07T02:49:07+00:00 from `C:\Users\charl\OneDrive\Documents\Official Project\Hallucination\agentloop-sec\results\als.sqlite`. Registry state as of None – None (UTC). Claims about nonexistence are valid only as of those check times.

## Headline

- Runs: **0**; resolved packages: **0** (unresolved imports excluded: 0)
- Prompt-level hallucination rate: **—**
- Package-level hallucination rate: **—**
- Squattable (exists, young or obscure): **—**
- Distinct fake names: **0** — R@2 —, R@3 —, R@5 —; seen across ≥2 models: 0

## Recurring fake names — what a defender should pre-block

Not a target list: every name below is blocked by the shim, and none was ever registered anywhere.

| # | ecosystem | name | runs | prompts | models | framings |
|---:|---|---|---:|---:|---|---|

### By model

| group | runs | packages | hallucinated | prompt-level | package-level | squattable |
|---|---:|---:|---:|---:|---:|---:|

### By framing

| group | runs | packages | hallucinated | prompt-level | package-level | squattable |
|---|---:|---:|---:|---:|---:|---:|

### By obscurity

| group | runs | packages | hallucinated | prompt-level | package-level | squattable |
|---|---:|---:|---:|---:|---:|---:|

### By ecosystem

| group | runs | packages | hallucinated | prompt-level | package-level | squattable |
|---|---:|---:|---:|---:|---:|---:|

### By domain

| group | runs | packages | hallucinated | prompt-level | package-level | squattable |
|---|---:|---:|---:|---:|---:|---:|

## Shim evaluation

Policy version(s): 2026-11-06.1. Cases: {'hallucinated': 0, 'real': 115, 'typo': 50, 'squattable': 0}

- Catch rate (blocked / hallucinated): **—**
- False-positive rate (blocked or flagged / real control): **0.9%** (hard blocks: 0.0%)
- Typo variants intercepted: 100.0%; squattable names flagged: —
- Latency cold: p50 357.9 ms, p95 513.8 ms (n=165)
- Latency warm: p50 0.0 ms, p95 0.5 ms (n=165)

False positives (reported, not hidden):

- `pyside6-webengine` → flag: first release 31d before check (< 180d); 0 downloads/30d (< 1000)
