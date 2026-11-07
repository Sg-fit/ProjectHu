"""Deterministic runner for tests and dry runs. Never part of reported results."""

from __future__ import annotations

from .base import RawOutput


class StubRunner:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.key = cfg.get("key", "stub")
        # responses: {prompt_text_or_id: text} or a callable(prompt, params) -> text
        self.responses = cfg.get("responses", {})

    def complete(self, prompt: str, params: dict) -> RawOutput:
        r = self.responses
        if callable(r):
            text = r(prompt, params)
        else:
            text = r.get(params.get("prompt_id"), r.get(prompt, "No libraries needed; use the standard library."))
        return RawOutput(text=text, served_model="stub", stop_reason="end_turn", input_tokens=0,
                         output_tokens=0, cost_usd=0.0, latency_ms=0.0, params={"run_idx": params.get("run_idx")})
