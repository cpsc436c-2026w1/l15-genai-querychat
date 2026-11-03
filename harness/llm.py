"""Model calls for the harness: one chat completion through the OpenAI SDK (Groq is OpenAI-compatible), a strict
JSON schema on the reply, tokens and wall-clock latency from the call, cost from list prices.

Same request shape as evals/correctness/solver.py; kept separate so the harness does not import inspect_ai.
provider "fake" returns replies from a dict, for tests without API calls."""

from __future__ import annotations

import re
import time

PROVIDERS = {
    "groq": dict(base_url="https://api.groq.com/openai/v1", key="GROQ_API_KEY"),
    "openai": dict(base_url=None, key="OPENAI_API_KEY"),
}
MODEL_PROVIDER = {"qwen/qwen3.8-27b": "groq", "gpt-5.4-nano": "openai", "gpt-5.4-mini": "openai"}
MAX_OUTPUT_TOKENS = 6000

# USD per 1M tokens: input, cached input, output. Same table and date as evals/correctness/report.py:
# console.groq.com/docs/models and developers.openai.com/api/docs/pricing, read 2026-11-02.
PRICES_DATE = "2026-11-02"
PRICES = {
    "qwen/qwen3.8-27b": (0.80, None, 4.00),
    "gpt-5.4-mini": (0.75, 0.075, 4.50),
    "gpt-5.4-nano": (0.20, 0.02, 1.25),
}


def cost_usd(model: str, tokens_in: int, tokens_cached: int, tokens_out: int) -> float:
    p = PRICES.get(model)
    if not p:
        return 0.0
    pin, pc, pout = p
    unc = tokens_in - (tokens_cached if pc else 0)
    return (unc * pin + (tokens_cached * pc if pc else 0) + tokens_out * pout) / 1e6


_clients: dict = {}


def _client(provider: str):
    if provider not in _clients:
        from openai import OpenAI

        from harness.keys import require

        cfg = PROVIDERS[provider]
        _clients[provider] = OpenAI(base_url=cfg["base_url"], api_key=require(cfg["key"]), max_retries=0,
                                    timeout=120)
    return _clients[provider]


_RETRY_AFTER = re.compile(r"try again in ([\d.]+)(ms|s)", re.I)


def chat_json(model: str, messages: list[dict], schema: dict, name: str = "answer", provider: str | None = None,
              fake: dict | None = None, rate_limit_retries: int = 4) -> dict:
    """One completion constrained by `schema`. Returns text, refusal, tokens, cost, latency, error.

    Rate-limit waits (HTTP 429) are retried here and counted in `rate_limited`; they are not schema retries."""
    provider = provider or MODEL_PROVIDER.get(model, "openai")
    out = dict(text="", refusal=None, tokens_in=0, tokens_cached=0, tokens_out=0, cost_usd=0.0, latency_s=0.0,
               error=None, finish_reason=None, rate_limited=0)
    if provider == "fake":
        reply = (fake or {}).get(messages[1]["content"], "")  # keyed by the first user message
        out["text"] = reply.pop(0) if isinstance(reply, list) else reply
        return out
    body = dict(model=model, messages=messages, max_completion_tokens=MAX_OUTPUT_TOKENS,
                response_format={"type": "json_schema", "json_schema": {"name": name, "schema": schema,
                                                                        "strict": True}})
    if provider == "groq":
        body["extra_body"] = {"reasoning_format": "parsed"}  # as in the eval: thinking kept out of content
    for attempt in range(rate_limit_retries + 1):
        t0 = time.perf_counter()
        try:
            r = _client(provider).chat.completions.create(**body)
        except Exception as e:
            out["latency_s"] = round(time.perf_counter() - t0, 3)
            out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
            if "RateLimit" in type(e).__name__ and attempt < rate_limit_retries:
                m = _RETRY_AFTER.search(str(e))
                out["rate_limited"] += 1
                time.sleep(min((float(m.group(1)) / (1000 if m.group(2) == "ms" else 1)) if m else 3.0, 30) + 1)
                continue
            return out
        out["latency_s"] = round(time.perf_counter() - t0, 3)
        out["error"] = None
        msg = r.choices[0].message
        out["text"] = msg.content or ""
        out["refusal"] = getattr(msg, "refusal", None)
        out["finish_reason"] = r.choices[0].finish_reason
        u = r.usage
        if u:
            out["tokens_in"] = u.prompt_tokens or 0
            out["tokens_out"] = u.completion_tokens or 0
            pd_ = getattr(u, "prompt_tokens_details", None)
            out["tokens_cached"] = (getattr(pd_, "cached_tokens", 0) or 0) if pd_ else 0
        out["cost_usd"] = cost_usd(model, out["tokens_in"], out["tokens_cached"], out["tokens_out"])
        return out
    return out
