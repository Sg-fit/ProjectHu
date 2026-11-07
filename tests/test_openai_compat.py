import json

import pytest

from als.runners.base import make_runner
from als.runners.openai_compat import MissingKey, OpenAICompatRunner


def _fake_urlopen(captured):
    class Resp:
        def __init__(self, body):
            self._b = body
        def read(self):
            return self._b
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def fake(req, timeout=None):
        captured["auth"] = req.headers.get("Authorization")
        captured["body"] = json.loads(req.data.decode())
        payload = {
            "model": "served-model-x",
            "choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 2},
        }
        return Resp(json.dumps(payload).encode())
    return fake


def test_presets_resolve():
    r = make_runner({"key": "g", "provider": "groq", "model_id": "llama-3.3-70b-versatile"})
    assert isinstance(r, OpenAICompatRunner)
    assert r.base_url == "https://api.groq.com/openai/v1" and r.api_key_env == "GROQ_API_KEY"
    r2 = make_runner({"key": "n", "provider": "nvidia", "model_id": "meta/llama-3.3-70b-instruct"})
    assert r2.base_url == "https://integrate.api.nvidia.com/v1" and r2.api_key_env == "NVIDIA_API_KEY"


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    r = make_runner({"key": "g", "provider": "groq", "model_id": "m"})
    with pytest.raises(MissingKey):
        r.complete("hi", {"system": "s", "run_idx": 0})


def test_complete_parses_and_sends(monkeypatch):
    captured = {}
    monkeypatch.setenv("GROQ_API_KEY", "secret-should-not-leak")
    monkeypatch.setattr("als.runners.openai_compat.urllib.request.urlopen", _fake_urlopen(captured))
    r = make_runner({"key": "g", "provider": "groq", "model_id": "llama-3.3-70b-versatile",
                     "temperature": 0.7, "seed_base": 1000})
    out = r.complete("make a scraper", {"system": "sys", "run_idx": 3, "max_tokens": 50})
    assert out.text == "pong" and out.served_model == "served-model-x" and out.stop_reason == "stop"
    assert out.input_tokens == 11 and out.output_tokens == 2
    # request shape
    assert captured["auth"] == "Bearer secret-should-not-leak"
    assert captured["body"]["model"] == "llama-3.3-70b-versatile"
    assert captured["body"]["seed"] == 1003                      # seed_base + run_idx
    assert captured["body"]["messages"][0] == {"role": "system", "content": "sys"}
    # the key must never appear in the provenance params we persist
    assert "secret-should-not-leak" not in json.dumps(out.params)
    assert out.params["endpoint"] == "https://api.groq.com/openai/v1"


def test_http_error_message_has_no_key(monkeypatch):
    import urllib.error

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-secret")

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
    monkeypatch.setattr("als.runners.openai_compat.urllib.request.urlopen", boom)
    r = make_runner({"key": "n", "provider": "nvidia", "model_id": "m", "max_retries": 0})
    with pytest.raises(RuntimeError) as ei:
        r.complete("hi", {"system": "s", "run_idx": 0})
    assert "nvapi-secret" not in str(ei.value) and "401" in str(ei.value)
