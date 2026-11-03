"""inspect_ai solver: one chat completion per question, answer constrained by the JSON schema.

Both providers are called through the OpenAI SDK (Groq serves an OpenAI-compatible API), so the request is
the same everywhere: system prompt + question + response_format json_schema. Recorded per sample in the
store: the raw reply, Qwen's reasoning text if the provider returns it, tokens in/out/cached/reasoning
(from the provider's usage), wall-clock latency of the call, retries, and any API error.

provider "fake" replays hand-made replies from tests/fake_replies.json, to test the whole pipeline
(task, scorers, report) without calling a model."""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

from inspect_ai.solver import Generate, TaskState, solver

from harness.inspect_model import record_usage, sdk_model
from harness.prompts import answer_json_schema, system_prompt

PROVIDERS = {
    "groq": dict(base_url="https://api.groq.com/openai/v1", key="GROQ_API_KEY"),
    "openai": dict(base_url=None, key="OPENAI_API_KEY"),
}
MAX_OUTPUT_TOKENS = 6000  # bounds spend on a runaway reasoning trace
FAKE = Path(__file__).resolve().parent / "tests" / "fake_replies.json"

_clients = {}


def _client(provider: str):
    if provider not in _clients:
        from openai import OpenAI

        from harness.keys import require

        cfg = PROVIDERS[provider]
        _clients[provider] = OpenAI(base_url=cfg["base_url"], api_key=require(cfg["key"]), max_retries=0,
                                    timeout=120)
    return _clients[provider]


def request_body(provider: str, model: str, question: str, config: str) -> dict:
    body = dict(
        model=model,
        messages=[{"role": "system", "content": system_prompt(config)}, {"role": "user", "content": question}],
        response_format={"type": "json_schema",
                         "json_schema": {"name": "answer", "schema": answer_json_schema(), "strict": True}},
        max_completion_tokens=MAX_OUTPUT_TOKENS,
    )
    if provider == "groq":
        body["extra_body"] = {"reasoning_format": "parsed"}  # Qwen's thinking comes back in message.reasoning
    return body


_RETRY_AFTER = re.compile(r"try again in ([\d.]+)(ms|s)", re.I)


def call_model(provider: str, model: str, question: str, config: str, max_retries: int = 4) -> dict:
    out = dict(text="", reasoning=None, tokens_in=0, tokens_out=0, tokens_cached=0, tokens_reasoning=0,
               latency_s=None, retries=0, error=None, finish_reason=None)
    if provider == "fake":
        fake = json.loads(FAKE.read_text())
        out.update(text=fake.get(f"{model}|{question}", fake.get(question, "")), latency_s=0.0)
        return out
    for attempt in range(max_retries + 1):
        out["retries"] = attempt
        t0 = time.perf_counter()
        try:
            r = _client(provider).chat.completions.create(**request_body(provider, model, question, config))
        except Exception as e:
            out["latency_s"] = round(time.perf_counter() - t0, 3)
            out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
            if "RateLimit" in type(e).__name__ and attempt < max_retries:
                m = _RETRY_AFTER.search(str(e))
                time.sleep(min((float(m.group(1)) / (1000 if m.group(2) == "ms" else 1)) if m else 3.0, 30) + 1)
                continue
            return out
        out["latency_s"] = round(time.perf_counter() - t0, 3)
        out["error"] = None
        msg = r.choices[0].message
        out["text"] = msg.content or ""
        out["reasoning"] = getattr(msg, "reasoning", None) or (msg.model_extra or {}).get("reasoning")
        out["finish_reason"] = r.choices[0].finish_reason
        u = r.usage
        if u:
            out["tokens_in"] = u.prompt_tokens or 0
            out["tokens_out"] = u.completion_tokens or 0
            pd_ = getattr(u, "prompt_tokens_details", None)
            cd = getattr(u, "completion_tokens_details", None)
            out["tokens_cached"] = (getattr(pd_, "cached_tokens", 0) or 0) if pd_ else 0
            out["tokens_reasoning"] = (getattr(cd, "reasoning_tokens", 0) or 0) if cd else 0
        return out
    return out


@solver
def schema_answer(provider: str, model: str, config: str = "baseline"):
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        res = await asyncio.to_thread(call_model, provider, model, state.input_text, config)
        for k, v in res.items():
            state.store.set(k, v)
        state.store.set("model", model)
        state.store.set("provider", provider)
        state.store.set("config", config)
        state.store.set("system_prompt_chars", len(system_prompt(config)))
        state.output.completion = res["text"] or (f"[ERROR] {res['error']}" if res["error"] else "")
        record_usage(sdk_model(provider, model), res["tokens_in"], res["tokens_out"], res["tokens_cached"])
        return state

    return solve
