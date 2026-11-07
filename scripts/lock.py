"""Regenerate requirements.lock with per-file sha256 hashes from the PyPI JSON API.

Run:  python scripts/lock.py

Runtime deps are intentionally minimal (PyYAML only). Dev/test deps are not
pinned here; generate those with `pip-compile --generate-hashes` if you want a
locked CI environment. Thematic: a tool that guards the install path pins its
own supply chain with hashes.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = [("PyYAML", "6.0.3")]


def file_hashes(pkg: str, ver: str) -> list[str]:
    url = f"https://pypi.org/pypi/{pkg}/{ver}/json"
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.load(r)
    return sorted({f["digests"]["sha256"] for f in data["urls"]})


def main() -> None:
    lines = [
        "# Runtime lock for agentloop-sec (hash-pinned).",
        "# Thematic note: a tool that defends the install path pins its own deps with",
        "# hashes, so it can never itself install a swapped artifact. Verify with:",
        "#   pip install --require-hashes -r requirements.lock",
        "# Regenerate with: python scripts/lock.py  (pulls digests from the PyPI JSON API)",
        "",
    ]
    for pkg, ver in RUNTIME:
        hs = file_hashes(pkg, ver)
        lines.append(f"{pkg}=={ver} \\")
        for i, h in enumerate(hs):
            lines.append(f"    --hash=sha256:{h}" + (" \\" if i < len(hs) - 1 else ""))
        print(f"{pkg} {ver}: {len(hs)} file hashes pinned")
    (ROOT / "requirements.lock").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
