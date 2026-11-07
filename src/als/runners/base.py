"""Runner protocol: anything that turns a prompt into raw model text."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class RawOutput:
    text: str
    served_model: str | None = None
    stop_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float = 0.0
    latency_ms: float | None = None
    params: dict = field(default_factory=dict)  # exactly what was sent, minus the prompt text


class Runner(Protocol):
    key: str

    def complete(self, prompt: str, params: dict) -> RawOutput:
        """params always carries: system (str), run_idx (int), max_tokens (int)."""
        ...


def make_runner(cfg: dict) -> Runner:
    provider = cfg["provider"]
    if provider == "anthropic":
        from .api import AnthropicRunner
        return AnthropicRunner(cfg)
    if provider == "ollama":
        from .local import OllamaRunner
        return OllamaRunner(cfg)
    if provider == "stub":
        from .stub import StubRunner
        return StubRunner(cfg)
    if provider in ("openai_compat", "nvidia", "groq", "openai"):
        from .openai_compat import OpenAICompatRunner
        if provider != "openai_compat":
            cfg = {**cfg, "preset": cfg.get("preset", provider)}
        return OpenAICompatRunner(cfg)
    raise ValueError(f"unknown provider {provider!r}")
