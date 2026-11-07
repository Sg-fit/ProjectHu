# Benign marker payload — procedure

This file documents how to build the **benign** demo distribution by hand. It is
a deliberate human step: the project never scripts the creation of an
install-time payload.

## What the payload must and must not do

- **Must:** on build/install, write a single marker file
  `MARKER_proof_of_execution.txt` into the system temp directory, and print one
  line to stdout. That is the whole proof of code execution.
- **Must not:** touch the network, write outside the temp directory, persist
  anything, or do anything a reviewer would not immediately understand. No
  obfuscation.

## Build it (on the lab host, inside the isolated network only)

1. Make a throwaway directory `pkg/` named after the target fake package.
2. Add a `pyproject.toml`/`setup.py` whose **build step** performs the two benign
   actions above — a `setup.py` with a custom `build_py`/`install` command, or a
   `pyproject.toml` build backend hook, is the usual way. Keep the code to a few
   lines, commented, in plain sight.
3. Build the sdist: `python -m build --sdist` (or `python setup.py sdist`).
4. Copy the resulting `dist/<name>-<version>.tar.gz` into
   `../registry/packages/` on the lab host. **Do not upload it anywhere.**

The local registry server will immediately list and serve it; its first-release
date is the file's mtime, so the shim sees it as a brand-new package.

## Verify the marker after an unguarded install

```bash
docker compose exec target cat "$TMPDIR/MARKER_proof_of_execution.txt" 2>/dev/null \
  || docker compose exec target cat /tmp/MARKER_proof_of_execution.txt
```

The marker's presence is the demonstration. Delete it between takes so each
recording starts clean:

```bash
docker compose exec target rm -f /tmp/MARKER_proof_of_execution.txt
```

## Narration checklist for the recording

- State that the registry is local and nothing was ever published publicly.
- Show the install **succeeding** and the marker appearing (the gap).
- Show the **same** command through `als-shim` being **blocked** (the fix).
- Keep the recurring-names table framed as *what a defender must pre-block*,
  never as a to-do list.
