"""Local open models via an Ollama server (stdlib HTTP only).

Fixed temperature; seed = seed_base + run_idx, so each of the 5 repeats is an
independent sample that is still reproducible.
"""

from __future__ import annotations

import json
import time
import urllib.request

from .base import RawOutput


class OllamaRunner:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.key = cfg["key"]
        self.model_id = cfg["model_id"]
        self.endpoint = cfg.get("endpoint", "http://localhost:11434").rstrip("/")

    def complete(self, prompt: str, params: dict) -> RawOutput:
        options = {
            "temperature": float(self.cfg.get("temperature", 0.7)),
            "seed": int(self.cfg.get("seed_base", 0)) + int(params.get("run_idx", 0)),
            "num_predict": int(params.get("max_tokens") or self.cfg.get("max_tokens", 4096)),
        }
        body = {
            "model": self.model_id,
            "stream": False,
            "options": options,
            "messages": [
                {"role": "system", "content": params["system"]},
                {"role": "user", "content": prompt},
            ],
        }
        req = urllib.request.Request(
            f"{self.endpoint}/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
        )
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=float(self.cfg.get("timeout_s", 600))) as resp:
            data = json.loads(resp.read())
        latency = (time.perf_counter() - t0) * 1000
        return RawOutput(
            text=(data.get("message") or {}).get("content", ""),
            served_model=data.get("model", self.model_id),
            stop_reason=data.get("done_reason"),
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
            cost_usd=0.0,
            latency_ms=latency,
            params={"model": self.model_id, "options": options, "run_idx": params.get("run_idx")},
        )
