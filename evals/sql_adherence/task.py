"""inspect_ai task: does the model's SQL run? The correctness questions, scorers and models, three ways of asking.

    uv run inspect eval evals/sql_adherence/task.py -T provider=groq -T model=qwen/qwen3.8-27b -T variant=pydantic \
        --epochs 3 --log-dir logs/sql_adherence

variant:
  baseline         as the correctness eval: the provider's strict JSON-schema mode, no check on the SQL itself
  pydantic         no schema mode: the prompt asks for the JSON. The reply is parsed into CheckedAnswer, whose sql
                   validator (validator.py) parses it with sqlglot, allows one SELECT over known tables and columns,
                   and runs EXPLAIN in DuckDB. On a failure the error goes back to the model once (one retry)
  pydantic_schema  the same validator and retry, with the strict JSON-schema mode as in baseline

The scorers are the correctness eval's (value_correct first). Retries used, the first failure and the extra tokens
are in each sample's store."""

from __future__ import annotations

import asyncio
import json
import re

from inspect_ai import Task, task
from inspect_ai.solver import Generate, TaskState, solver
from pydantic import ValidationError

from evals.correctness.scorers import ALL_SCORERS
from evals.correctness.solver import call_model
from evals.correctness.task import dataset
from evals.sql_adherence.validator import CheckedAnswer
from harness.inspect_model import record_usage, sdk_model
from harness.keys import load_keys
from harness.prompts import system_prompt

VARIANTS = ("baseline", "pydantic", "pydantic_schema")
RETRY_PROMPT = ("Your reply failed validation: {error}\nReply again with the corrected JSON object only: one DuckDB "
                "SELECT in the sql field, with nothing before or after it.")


def validation_error(text: str) -> str | None:
    """None when the reply parses into CheckedAnswer, else the message a retry sends back."""
    t = (text or "").strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    try:
        CheckedAnswer.model_validate(json.loads(m.group(1) if m else t))
    except json.JSONDecodeError as e:
        return f"the reply is not JSON ({e.msg} at character {e.pos})"
    except ValidationError as e:
        return "; ".join(f"{'.'.join(map(str, x['loc'])) or 'reply'}: {x['msg'].removeprefix('Value error, ')}"
                         for x in e.errors())
    return None


def ask(provider: str, model: str, question: str, variant: str) -> dict:
    use_schema = variant != "pydantic"
    first = call_model(provider, model, question, "baseline", use_schema=use_schema)
    out = dict(first, validator_retries=0, validation_error=None, first_text=None, first_tokens_in=first["tokens_in"],
               first_tokens_out=first["tokens_out"])
    if variant == "baseline" or first["error"]:
        return out
    err = validation_error(first["text"])
    if err is None:
        return out
    messages = [{"role": "system", "content": system_prompt("baseline")}, {"role": "user", "content": question},
                {"role": "assistant", "content": first["text"]},
                {"role": "user", "content": RETRY_PROMPT.format(error=err)}]
    second = call_model(provider, model, question, "baseline", use_schema=use_schema, messages=messages)
    out.update(second, validator_retries=1, validation_error=err, first_text=first["text"],
               first_tokens_in=first["tokens_in"], first_tokens_out=first["tokens_out"])
    for k in ("tokens_in", "tokens_out", "tokens_cached", "tokens_reasoning"):
        out[k] = (first[k] or 0) + (second[k] or 0)
    out["latency_s"] = round((first["latency_s"] or 0) + (second["latency_s"] or 0), 3)
    out["second_error"] = validation_error(second["text"]) if not second["error"] else second["error"]
    return out


@solver
def checked_answer(provider: str, model: str, variant: str):
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        res = await asyncio.to_thread(ask, provider, model, state.input_text, variant)
        for k, v in res.items():
            state.store.set(k, v)
        state.store.set("model", model)
        state.store.set("provider", provider)
        state.store.set("config", variant)
        state.output.completion = res["text"] or (f"[ERROR] {res['error']}" if res["error"] else "")
        record_usage(sdk_model(provider, model), res["tokens_in"], res["tokens_out"], res["tokens_cached"])
        return state

    return solve


@task
def sql_adherence(provider: str = "groq", model: str = "qwen/qwen3.8-27b", variant: str = "baseline",
                  ids: str = "") -> Task:
    if variant not in VARIANTS:
        raise ValueError(f"variant: {' | '.join(VARIANTS)}")
    if provider != "fake":
        load_keys()
    return Task(
        dataset=dataset(ids),
        solver=checked_answer(provider=provider, model=model, variant=variant),
        scorer=[s() for s in ALL_SCORERS],
        model=sdk_model(provider, model),
        metadata={"provider": provider, "model_id": model, "config": variant},
        name=f"sql_adherence_{variant}_{model.split('/')[-1]}",
    )
