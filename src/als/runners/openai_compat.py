"""Runner for any OpenAI-compatible /chat/completions endpoint (stdlib HTTP only).

Covers NVIDIA NIM (https://integrate.api.nvidia.com/v1) and Groq
(https://api.groq.com/openai/v1), which both serve open models (Llama, Qwen,
GPT-OSS, DeepSeek, ...) behind the OpenAI chat schema. Using these as the
"two local/open models" of the study is what makes the recurrence finding a
property of the agent loop rather than of one vendor.

The API key is read from the environment variable named by `api_key_env` at
call time and sent only in the Authorization header. It is never logged, never
stored in the run's params_json, and never echoed.

Sampling: these endpoints DO accept temperature + seed (unlike the Claude
models), so repeats are independent samples at a fixed temperature with
seed = seed_base + run_idx. That asymmetry with the Claude runner is recorded
per run and must be stated in the writeup.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .base import RawOutput

PRESETS = {
    "nvidia": {"base_url": "https://integrate.api.nvidia.com/v1", "api_key_env": "NVIDIA_API_KEY"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "api_key_env": "GROQ_API_KEY"},
    "openai": {"base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY"},
}

# Groq sits behind Cloudflare, which 1010-blocks the default `Python-urllib/x.y`
# user-agent. A normal UA avoids it; harmless on the other providers.
USER_AGENT = "agentloop-sec/0.1 (+https://github.com/Sg-fit/ProjectHu)"


class MissingKey(RuntimeError):
    pass


class OpenAICompatRunner:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.key = cfg["key"]
        self.model_id = cfg["model_id"]
        preset = PRESETS.get(cfg.get("preset", ""), {})
        self.base_url = (cfg.get("base_url") or preset.get("base_url", "")).rstrip("/")
        self.api_key_env = cfg.get("api_key_env") or preset.get("api_key_env")
        if not self.base_url or not self.api_key_env:
            raise ValueError(f"{self.key}: need base_url + api_key_env (or a known preset)")
        price = cfg.get("pricing_per_mtok") or {}
        self.in_price = float(price.get("input", 0))
        self.out_price = float(price.get("output", 0))
        self.timeout = float(cfg.get("timeout_s", 180))
        self.max_retries = int(cfg.get("max_retries", 4))

    def _auth(self) -> str:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise MissingKey(f"{self.key}: environment variable {self.api_key_env} is not set")
        return key

    def _post(self, body: dict) -> tuple[dict, float]:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=data,
            headers={"Authorization": f"Bearer {self._auth()}", "Content-Type": "application/json",
                     "Accept": "application/json", "User-Agent": USER_AGENT},
        )
        delay = 2.0
        for attempt in range(self.max_retries + 1):
            t0 = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read()), (time.perf_counter() - t0) * 1000
            except urllib.error.HTTPError as e:
                payload = e.read().decode("utf-8", "replace")[:500] if e.fp else ""
                if e.code in (408, 409, 429) or e.code >= 500:
                    if attempt < self.max_retries:
                        time.sleep(delay)
                        delay *= 2
                        continue
                raise RuntimeError(f"HTTP {e.code} from {self.key}: {payload}") from None
            except urllib.error.URLError as e:
                if attempt < self.max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise RuntimeError(f"connection error to {self.key}: {e.reason}") from None
            except (TimeoutError, OSError) as e:
                # A read timeout mid-response raises a bare TimeoutError (socket),
                # not URLError. Treat it like any transient connection failure.
                if attempt < self.max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise RuntimeError(f"timed out after {self.timeout:.0f}s contacting {self.key}: {e}") from None
        raise RuntimeError(f"{self.key}: exhausted retries")

    def complete(self, prompt: str, params: dict) -> RawOutput:
        body = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": params["system"]},
                {"role": "user", "content": prompt},
            ],
            "temperature": float(self.cfg.get("temperature", 0.7)),
            "max_tokens": int(params.get("max_tokens") or self.cfg.get("max_tokens", 4096)),
            "seed": int(self.cfg.get("seed_base", 0)) + int(params.get("run_idx", 0)),
            "stream": False,
        }
        if self.cfg.get("top_p") is not None:
            body["top_p"] = float(self.cfg["top_p"])
        data, latency = self._post(body)
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        usage = data.get("usage") or {}
        it, ot = usage.get("prompt_tokens"), usage.get("completion_tokens")
        cost = ((it or 0) * self.in_price + (ot or 0) * self.out_price) / 1e6
        # params echoed for provenance: everything EXCEPT the key and the prompt text
        sent = {k: v for k, v in body.items() if k != "messages"}
        sent["run_idx"] = params.get("run_idx")
        sent["endpoint"] = self.base_url
        return RawOutput(
            text=msg.get("content") or "",
            served_model=data.get("model", self.model_id),
            stop_reason=choice.get("finish_reason"),
            input_tokens=it,
            output_tokens=ot,
            cost_usd=cost,
            latency_ms=latency,
            params=sent,
        )
