"""Load + validate the prompt corpus and framing system prompts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

FRAMINGS = ("f1", "f2", "f3", "f4")
OBSCURITY = ("mainstream", "niche")
ECOSYSTEMS = ("pypi", "npm")
REQUIRED = ("id", "text", "framing", "domain", "ecosystem", "obscurity")


@dataclass(frozen=True)
class Prompt:
    id: str
    text: str
    framing: str
    domain: str
    ecosystem: str
    obscurity: str
    task_id: str = ""


class CorpusError(ValueError):
    pass


def load_prompts(path: str | Path) -> list[Prompt]:
    prompts, seen = [], set()
    for ln, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            raise CorpusError(f"{path}:{ln}: invalid JSON: {e}") from e
        missing = [k for k in REQUIRED if not rec.get(k)]
        if missing:
            raise CorpusError(f"{path}:{ln}: missing {missing}")
        if rec["framing"] not in FRAMINGS:
            raise CorpusError(f"{path}:{ln}: framing {rec['framing']!r} not in {FRAMINGS}")
        if rec["obscurity"] not in OBSCURITY:
            raise CorpusError(f"{path}:{ln}: obscurity {rec['obscurity']!r} not in {OBSCURITY}")
        if rec["ecosystem"] not in ECOSYSTEMS:
            raise CorpusError(f"{path}:{ln}: ecosystem {rec['ecosystem']!r} not in {ECOSYSTEMS}")
        if rec["id"] in seen:
            raise CorpusError(f"{path}:{ln}: duplicate id {rec['id']!r}")
        seen.add(rec["id"])
        prompts.append(Prompt(**{k: rec[k] for k in REQUIRED}, task_id=rec.get("task_id", "")))
    return prompts


def load_framings(path: str | Path) -> dict[str, str]:
    """framing id -> system prompt."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    out = {}
    for f in FRAMINGS:
        if f not in data or "system" not in data[f]:
            raise CorpusError(f"{path}: framing {f} needs a `system` prompt")
        out[f] = data[f]["system"].strip()
    return out
