"""`als-shim` - guard package installs.

  als-shim check [--ecosystem pypi|npm] [--json] NAME...      verdicts only, installs nothing
  als-shim install [--ecosystem pypi|npm] [--yes] NAME...     guarded `pip install` / `npm install`
  als-shim exec [--yes] -- COMMAND...                         guard an arbitrary command (passthrough
                                                              if it is not an install)
Exit codes: 0 ok, 2 usage, 3 blocked, 4 needs human approval.
"""

from __future__ import annotations

import argparse
import json
import sys

from ..store import Store
from .interpose import EXIT_BLOCKED, EXIT_NEEDS_APPROVAL, EXIT_OK, Shim, default_db, run_guarded
from .policy import BLOCK, FLAG, load_policy


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--policy", help="policy.yaml path (default: config/policy.yaml)")
    p.add_argument("--db", help=f"cache database (default: $ALS_SHIM_DB or {default_db()})")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="als-shim", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="print verdicts for package names")
    _common(c)
    c.add_argument("--ecosystem", default="pypi", choices=["pypi", "npm"])
    c.add_argument("--json", action="store_true")
    c.add_argument("names", nargs="+")

    i = sub.add_parser("install", help="guarded install")
    _common(i)
    i.add_argument("--ecosystem", default="pypi", choices=["pypi", "npm"])
    i.add_argument("--yes", action="store_true", help="approve flagged (never blocked) packages")
    i.add_argument("--dry-run", action="store_true")
    i.add_argument("names", nargs="+")

    e = sub.add_parser("exec", help="guard an arbitrary command")
    _common(e)
    e.add_argument("--yes", action="store_true")
    e.add_argument("--dry-run", action="store_true")
    e.add_argument("command", nargs=argparse.REMAINDER)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    policy = load_policy(args.policy)
    shim = Shim(policy, Store(args.db or default_db()))

    if args.cmd == "check":
        verdicts = shim.check(args.names, args.ecosystem)
        if args.json:
            print(json.dumps([v.to_dict() for v in verdicts], indent=2))
        else:
            for v in verdicts:
                print(f"{v.verdict.upper():5}  {v.ecosystem}:{v.name:30}  [{v.bucket}]  {'; '.join(v.reasons)}")
        if any(v.verdict == BLOCK for v in verdicts):
            return EXIT_BLOCKED
        if any(v.verdict == FLAG for v in verdicts):
            return EXIT_NEEDS_APPROVAL
        return EXIT_OK

    if args.cmd == "install":
        if args.ecosystem == "npm":
            cmd = ["npm", "install", *args.names]
        else:
            cmd = [sys.executable, "-m", "pip", "install", *args.names]
        return run_guarded(cmd, shim, approve_all_flags=args.yes, dry_run=args.dry_run)

    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    return run_guarded(command, shim, approve_all_flags=args.yes, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
