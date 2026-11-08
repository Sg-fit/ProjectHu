"""Connectivity test for the OpenAI-compatible providers (NVIDIA, Groq).

  python scripts/test_providers.py                 # test every provider whose key is set
  python scripts/test_providers.py groq nvidia     # test named providers
  python scripts/test_providers.py --list          # also list available models per provider
  python scripts/test_providers.py --model groq=llama-3.1-8b-instant

For each provider it:
  1. confirms the API key env var is set (presence only - the key is never printed),
  2. GETs /models to prove auth works and (with --list) shows what is available,
  3. runs one tiny completion through the real als runner and reports served model,
     finish reason, token usage and latency.

Exit code is non-zero if any requested provider fails.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from als.runners.openai_compat import PRESETS, USER_AGENT, MissingKey, OpenAICompatRunner  # noqa: E402

# Preferred ping models per provider (first one present in the catalog wins).
# Overridable with --model provider=id.
PREFERRED = {
    "groq": ["llama-3.1-8b-instant", "llama-3.3-70b-versatile", "openai/gpt-oss-20b"],
    "nvidia": ["nvidia/llama-3.1-nemotron-70b-instruct", "mistralai/mistral-large-2-instruct",
               "mistralai/mistral-large", "meta/llama2-70b", "databricks/dbrx-instruct",
               "ai21labs/jamba-1.5-large-instruct", "01-ai/yi-large",
               "ibm/granite-3.0-8b-instruct", "mistralai/mistral-7b-instruct-v0.3"],
    "openai": ["gpt-4o-mini"],
}
# Non-chat model families to skip when auto-picking (embeddings, vision-only,
# safety/guard, reward, rerankers, parsers, translators, detectors, etc.).
_NOT_CHAT = ("embed", "embedqa", "rerank", "reward", "guard", "safety", "nemoguard",
             "nemoretriever", "parse", "translate", "detector", "calibration", "diffusion",
             "nvclip", "deplot", "kosmos", "neva", "vila", "fuyu", "cosmos", "riva", "omni",
             "-vl-", "chatqa")
_CHAT_HINT = ("instruct", "chat", "-it", "gpt-oss", "versatile", "instant", "nemotron")
PING = "Reply with exactly the word: pong"
MAX_PING_ATTEMPTS = 8
PING_TIMEOUT_S = 25        # short, so a hung model fails fast and the sweep moves on


def chat_candidates(provider: str, available: list[str], override: str | None) -> list[str]:
    avail = set(available)
    ranked: list[str] = []
    if override:
        ranked.append(override)
    for m in PREFERRED.get(provider, []):
        if m in avail and m not in ranked:
            ranked.append(m)
    # then any catalog model that looks like a chat/instruct text model
    for m in available:
        low = m.lower()
        if m in ranked or any(b in low for b in _NOT_CHAT):
            continue
        if any(h in low for h in _CHAT_HINT):
            ranked.append(m)
    return ranked


def list_models(preset: dict) -> tuple[int, list[str], str | None]:
    key = os.environ.get(preset["api_key_env"])
    req = urllib.request.Request(preset["base_url"].rstrip("/") + "/models",
                                 headers={"Authorization": f"Bearer {key}", "Accept": "application/json",
                                          "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        return -1, [], f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
    except urllib.error.URLError as e:
        return -1, [], f"connection error: {e.reason}"
    ids = sorted(m.get("id", "") for m in data.get("data", []))
    return len(ids), ids, None


def test_provider(provider: str, model_override: str | None, show_list: bool) -> bool:
    preset = PRESETS.get(provider)
    if not preset:
        print(f"  {provider}: unknown provider")
        return False
    print(f"\n=== {provider} ({preset['base_url']}) ===")
    if not os.environ.get(preset["api_key_env"]):
        print(f"  SKIP: {preset['api_key_env']} not set in this shell's environment.")
        return False

    n, ids, err = list_models(preset)
    if err:
        print(f"  /models FAILED ({err})")
        return False
    print(f"  auth OK - {n} models available")
    if show_list:
        for mid in ids:
            print(f"      {mid}")
    elif ids:
        print(f"      e.g. {', '.join(ids[:6])}{' ...' if n > 6 else ''}")

    candidates = chat_candidates(provider, ids, model_override)
    if not candidates:
        print("  no chat-capable model found in the catalog to ping")
        return False
    last_err = None
    tried = candidates[:MAX_PING_ATTEMPTS]
    for model in tried:
        runner = OpenAICompatRunner({"key": f"{provider}-test", "provider": provider, "preset": provider,
                                     "model_id": model, "temperature": 0.0, "max_tokens": 16,
                                     "timeout_s": PING_TIMEOUT_S, "max_retries": 1})
        try:
            out = runner.complete(PING, {"system": "You are a terse assistant.", "run_idx": 0, "max_tokens": 16})
        except MissingKey as e:
            print(f"  completion FAILED: {e}")
            return False
        except RuntimeError as e:
            last_err = e
            reason = "timeout" if "timed out" in str(e).lower() else ("404" if "404" in str(e) or "not found" in str(e).lower() else "error")
            print(f"  '{model}' not usable ({reason}); trying next...")
            continue
        print(f"  completion OK - model='{out.served_model}' finish='{out.stop_reason}' "
              f"tokens in/out={out.input_tokens}/{out.output_tokens} latency={out.latency_ms:.0f}ms")
        print(f"      reply: {out.text.strip()[:80]!r}")
        print(f"      -> use this id in config/models.yaml: {model}")
        return True
    print(f"  completion FAILED: none of {len(tried)} candidates were callable (last error: {last_err})")
    print(f"      tried: {', '.join(tried)}")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("providers", nargs="*", help="providers to test (default: all with a key set)")
    ap.add_argument("--list", action="store_true", help="list every available model id per provider")
    ap.add_argument("--model", action="append", default=[], help="override ping model, e.g. --model groq=llama-3.1-8b-instant")
    a = ap.parse_args()

    overrides = dict(x.split("=", 1) for x in a.model)
    providers = a.providers or [p for p in ("groq", "nvidia", "openai") if os.environ.get(PRESETS[p]["api_key_env"])]
    if not providers:
        print("No provider API keys found in the environment. Set GROQ_API_KEY and/or NVIDIA_API_KEY and re-run.")
        print("  PowerShell:  $env:GROQ_API_KEY = '...'   ;  $env:NVIDIA_API_KEY = '...'")
        print("  bash:        export GROQ_API_KEY=...      ;  export NVIDIA_API_KEY=...")
        return 2

    results = {p: test_provider(p, overrides.get(p), a.list) for p in providers}
    ok = sum(results.values())
    print(f"\n{ok}/{len(results)} provider(s) OK: " +
          ", ".join(f"{p}={'OK' if v else 'FAIL'}" for p, v in results.items()))
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
