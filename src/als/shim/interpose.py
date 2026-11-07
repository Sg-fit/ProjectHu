"""The interposer. Sits between the agent's proposed command and the package
manager: model -> proposed command -> SHIM -> package manager -> environment.

It runs *before* execution. Nothing is installed until every name in the
command has a verdict, and the agent gets an explicit, actionable message on
block/flag - an opaque failure invites the agent to retry or route around it.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..extract import _REQ_LINE, _install_commands
from ..oracle import Oracle
from ..store import Store
from .policy import ALLOW, BLOCK, FLAG, Verdict, decide, load_policy

EXIT_OK, EXIT_USAGE, EXIT_BLOCKED, EXIT_NEEDS_APPROVAL = 0, 2, 3, 4


def default_db() -> str:
    return os.environ.get("ALS_SHIM_DB") or str(Path.home() / ".cache" / "als" / "shim.sqlite")


@dataclass
class Decision:
    command: list[str]
    ecosystem: str | None
    verdicts: list[Verdict] = field(default_factory=list)
    latency_ms: float = 0.0

    @property
    def blocked(self) -> list[Verdict]:
        return [v for v in self.verdicts if v.verdict == BLOCK]

    @property
    def flagged(self) -> list[Verdict]:
        return [v for v in self.verdicts if v.verdict == FLAG]

    @property
    def outcome(self) -> str:
        if self.blocked:
            return BLOCK
        if self.flagged:
            return FLAG
        return ALLOW


def _requirements_names(path: str) -> list[str]:
    names = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return names
    for ln in lines:
        s = ln.split("#")[0].strip()
        if not s or s.startswith("-"):
            continue
        m = _REQ_LINE.match(s)
        if m:
            names.append(m.group("name"))
    return names


def packages_in_command(argv: list[str]) -> tuple[str | None, list[str]]:
    """(ecosystem, names) for an install command; (None, []) if it is not one."""
    line = shlex.join(argv)
    exts = _install_commands(line)
    names = [e.name_raw for e in exts]
    eco = exts[0].ecosystem if exts else None
    # requirements files: pip install -r reqs.txt
    for i, tok in enumerate(argv):
        if tok in ("-r", "--requirement") and i + 1 < len(argv):
            names += _requirements_names(argv[i + 1])
            eco = eco or "pypi"
        elif tok.startswith("--requirement="):
            names += _requirements_names(tok.split("=", 1)[1])
            eco = eco or "pypi"
    seen, uniq = set(), []
    for n in names:
        if n.lower() not in seen:
            seen.add(n.lower())
            uniq.append(n)
    return eco, uniq


class Shim:
    def __init__(self, policy: dict | None = None, store: Store | None = None, oracle: Oracle | None = None):
        self.policy = policy or load_policy()
        self.store = store or Store(default_db())
        self.oracle = oracle or Oracle.from_policy(self.store, self.policy)

    def check(self, names: list[str], ecosystem: str = "pypi") -> list[Verdict]:
        return [decide(self.oracle.resolve(ecosystem, n), self.policy) for n in names]

    def evaluate(self, argv: list[str]) -> Decision:
        t0 = time.perf_counter()
        eco, names = packages_in_command(argv)
        d = Decision(argv, eco)
        if eco and names:
            d.verdicts = self.check(names, eco)
        d.latency_ms = (time.perf_counter() - t0) * 1000
        return d


def agent_message(d: Decision, approved: set[str]) -> str:
    """What the agent (and the human) sees. Specific and actionable on purpose."""
    cmd = shlex.join(d.command)
    lines = []
    if d.blocked:
        lines.append(f"[als-shim] BLOCKED before execution: {cmd}")
        for v in d.blocked:
            lines.append(f"  - {v.name} ({v.ecosystem}): {'; '.join(v.reasons)}.")
        lines.append("  This name was most likely hallucinated. Do NOT retry with spelling variants of it.")
        lines.append("  Use an established library you can verify exists, or implement the feature with the standard library.")
        lines.append("  Nothing was installed.")
    pending = [v for v in d.flagged if v.name not in approved]
    if pending:
        lines.append(f"[als-shim] NEEDS HUMAN APPROVAL: {cmd}")
        for v in pending:
            m = v.metadata
            facts = ", ".join(x for x in [
                f"first release {m['first_release'][:10]}" if m.get("first_release") else None,
                f"{m['downloads_30d']} downloads/30d" if m.get("downloads_30d") is not None else None,
                f"latest {m['latest_version']}" if m.get("latest_version") else None,
            ] if x)
            lines.append(f"  - {v.name} ({v.ecosystem}): {'; '.join(v.reasons)}." + (f" [{facts}]" if facts else ""))
        lines.append("  Ask the user to confirm these packages are intended. To proceed after review:")
        lines.append(f"    ALS_SHIM_APPROVE={','.join(v.name for v in pending)} <same command>")
        if not d.blocked:
            lines.append("  Nothing was installed.")
    return "\n".join(lines)


def run_guarded(argv: list[str], shim: Shim | None = None, *, approve: set[str] | None = None,
                approve_all_flags: bool = False, interactive: bool | None = None,
                dry_run: bool = False, out=sys.stderr) -> int:
    if not argv:
        print("[als-shim] no command given", file=out)
        return EXIT_USAGE
    shim = shim or Shim()
    d = shim.evaluate(argv)
    approved = set(approve or set())
    env_ok = os.environ.get("ALS_SHIM_APPROVE", "")
    approved |= {n.strip().lower() for n in env_ok.split(",") if n.strip()}
    if approve_all_flags:
        approved |= {v.name for v in d.flagged}

    if d.blocked:
        print(agent_message(d, approved), file=out)
        return EXIT_BLOCKED

    pending = [v for v in d.flagged if v.name not in approved]
    if pending:
        if interactive is None:
            interactive = sys.stdin.isatty() and sys.stderr.isatty()
        print(agent_message(d, approved), file=out)
        if not interactive:
            return EXIT_NEEDS_APPROVAL
        ans = input("[als-shim] Install anyway? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            return EXIT_NEEDS_APPROVAL

    if d.verdicts:
        print(f"[als-shim] allowed ({len(d.verdicts)} package(s), {d.latency_ms:.0f} ms): {shlex.join(argv)}", file=out)
    if dry_run:
        return EXIT_OK
    return subprocess.call(argv)
