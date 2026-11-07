"""Frontier API runner (Anthropic Messages API via the official SDK).

Notes for the methodology section:
- Current Claude models reject temperature/top_p/top_k, so sampling is the
  provider default; we record `effort` instead, which is the knob that exists.
- Thinking is adaptive and cannot be disabled on Opus 5.5; only the final text
  blocks are treated as the model's output (that is what an agent loop parses).
- Refusal fallbacks are off by default so the answering model is never swapped
  silently; `served_model` and `stop_reason` are recorded for every run.
"""

from __future__ import annotations

import time

from .base import RawOutput


class AnthropicRunner:
    def __init__(self, cfg: dict):
        import anthropic  # optional dependency: pip install agentloop-sec[api]

        self.cfg = cfg
        self.key = cfg["key"]
        self.model_id = cfg["model_id"]
        self.client = anthropic.Anthropic(max_retries=4)
        price = cfg.get("pricing_per_mtok") or {}
        self.in_price = float(price.get("input", 0))
        self.out_price = float(price.get("output", 0))

    def complete(self, prompt: str, params: dict) -> RawOutput:
        req = {
            "model": self.model_id,
            "max_tokens": int(params.get("max_tokens") or self.cfg.get("max_tokens", 8000)),
            "system": params["system"],
            "messages": [{"role": "user", "content": prompt}],
        }
        if self.cfg.get("effort"):
            req["output_config"] = {"effort": self.cfg["effort"]}
        sent = {k: v for k, v in req.items() if k not in ("messages", "system")}
        sent["run_idx"] = params.get("run_idx")

        t0 = time.perf_counter()
        if self.cfg.get("fallbacks"):
            resp = self.client.beta.messages.create(
                **req, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
            )
            sent["fallbacks"] = "default"
        else:
            resp = self.client.messages.create(**req)
        latency = (time.perf_counter() - t0) * 1000

        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        usage = resp.usage
        cost = (usage.input_tokens * self.in_price + usage.output_tokens * self.out_price) / 1e6
        return RawOutput(
            text=text,
            served_model=resp.model,
            stop_reason=resp.stop_reason,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=cost,
            latency_ms=latency,
            params=sent,
        )
