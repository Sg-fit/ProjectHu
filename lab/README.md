# Contained attack demo

Proves the hallucination-to-action gap is exploitable **without touching anything public**.

## Safety invariants (restated from the project hard rules)

1. **Nothing is ever registered on a public registry.** The only "registry" in
   this lab is `registry/server.py`, which serves files placed by hand in
   `registry/packages/` on the lab host.
2. **The target container has no internet egress.** `docker-compose.yml` puts it
   on an `internal: true` bridge network; its pip is pointed at
   `http://registry:8080/simple` only.
3. **The payload is benign.** It writes one marker file and prints one line. That
   is sufficient to prove code execution on install. No live malware, no
   persistence, no network.

## What runs where

| Service | Role |
|---|---|
| `registry` | Local PEP 503 index + PyPI-JSON endpoint. Serves `registry/packages/` read-only. No upload endpoint. |
| `target` | Clean container that executes the install command. pip can reach only `registry`. Has `als-shim` for the before/after. |

## The before/after (the spine of the video)

1. Take the **top recurring fake name** from `results/report.md` (e.g. the #1 row
   of the recurring-names table).
2. Build a benign distribution for that name and copy it into
   `registry/packages/` on the lab host. See [`demo/README.md`](demo/README.md)
   for the exact, benign marker procedure — this is a deliberate human step, so
   that creating an install-time payload is never automated.
3. **Unguarded:** in the target, run the install command the agent produced for
   that name. The install succeeds and the marker file appears — code execution,
   purely because the model invented a name that was pre-registered on the index.
4. **Guarded:** re-run the same command through `als-shim exec -- <command>`.
   The shim resolves the name against the index, and the demo shows two cases:
   - the name as a **local-only** young package → flagged for approval, or
   - the same name checked against **public PyPI** (`ALS_PYPI_BASE=https://pypi.org`),
     where it does not exist → **blocked**. Nothing installs.

On screen throughout: **local registry only — nothing was ever published publicly.**

## Running

```bash
cd lab
# build the shim wheel so the target image can install it offline
python -m pip wheel --no-deps -w agent/dist ..
docker compose build
docker compose up -d
# ... place the benign distribution in registry/packages/ by hand ...
docker compose exec target bash   # drive the before/after by hand, see demo/README.md
docker compose down -v
```

If Docker is unavailable, the same before/after runs on one host with two
terminals: `PACKAGES_DIR=./registry/packages python registry/server.py` in one,
and in the other a throwaway virtualenv with
`pip config set global.index-url http://localhost:8080/simple`. The isolation
guarantee is weaker without the `internal` network, so state that if you record
it this way.
