"""inspect_ai task: does the model's SQL run? The correctness questions, scorers and models, with four fixes.

    uv run inspect eval evals/sql_adherence/task.py -T provider=groq -T model=qwen/qwen3.8-27b -T variant=pydantic \
        --epochs 3 --log-dir logs/sql_adherence

The four fixes, after Huyen, AI Engineering ch. 2 (structured outputs):
  instructions  prompting: name the DuckDB dialect, ask for the query alone, give 3 short correct DuckDB examples
                (none of them an eval question). The column names and types are in the prompt in every variant
  json          constrained sampling: the provider's strict JSON-schema mode for the reply. Without it the prompt
                describes the four fields and the model writes the JSON on its own
  pydantic      test-time retry: the reply is parsed into CheckedAnswer (validator.py: sqlglot parse, one SELECT,
                known tables and columns, EXPLAIN in DuckDB). On a failure the error goes back to the model once
  cut           post-processing in the tool, the safe part: keep the reply's SQL up to the first semicolon that
                ends a complete statement (found with sqlglot, so a ";" in a string survives). Never rewrites
  rewrite       post-processing that rewrites: sqlglot transpile and near-miss column names, only when DuckDB
                cannot plan the SQL. It can change what a query means
  repair        the first version of the post-processing, used in "all" and the all-but-one runs: a plain cut at
                the first ";" plus comments dropped, then rewrite (repair.py: repair)
Every change the post-processing makes is logged in the sample's store.

variant: baseline (none of them), one fix, cut+pydantic, "all" (instructions, json, pydantic, repair) or
"all-<fix>" (all but one), e.g. all-json.
The scorers are the correctness eval's (value_correct first). Retries, repairs and the first reply are in the store."""

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
from evals.sql_adherence.repair import cut_first_statement, repair, rewrite
from evals.sql_adherence.validator import CheckedAnswer
from harness.inspect_model import record_usage, sdk_model
from harness.keys import load_keys
from harness.prompts import answer_json_schema, system_prompt

FIXES = ("instructions", "json", "pydantic", "repair")       # the four in "all" and the all-but-one variants
VARIANTS = ("baseline", "instructions", "json", "pydantic", "cut", "rewrite", "repair", "cut+pydantic",
            "json+pydantic", "json+cut+pydantic", "all",
            *(f"all-{f}" for f in FIXES))

REPLY_FORMAT = """
## Reply format

Reply with one JSON object and nothing else, with exactly these four fields:
{fields}
"""

INSTRUCTIONS = """
## DuckDB SQL

- The database is DuckDB. Write DuckDB SQL, with the exact column names and types listed in <tables>.
- The `sql` field holds the query alone: no semicolon, no comment, no text before or after it.
- Do not use SQL keywords (do, on, end, order) as table aliases.

Examples of correct DuckDB queries on these tables:
- "What is the largest tip on a cash trip?" -> SELECT MAX(tip_amount) AS max_tip FROM taxi WHERE payment_type = 2
- "How many trips ended in Queens?" -> SELECT COUNT(*) AS n FROM taxi t JOIN zones z ON t.DOLocationID = z.LocationID WHERE z.Borough = 'Queens'
- "What is the median trip distance on 3 January 2024?" -> SELECT quantile_cont(trip_distance, 0.5) AS median_miles FROM taxi WHERE CAST(tpep_pickup_datetime AS DATE) = DATE '2024-01-03'
"""

RETRY_PROMPT = ("Your reply failed validation: {error}\nReply again with the corrected JSON object only: one DuckDB "
                "SELECT in the sql field, with nothing before or after it.")


def fixes(variant: str) -> set[str]:
    if variant not in VARIANTS:
        raise ValueError(f"variant: {' | '.join(VARIANTS)}")
    if variant == "baseline":
        return set()
    if variant == "all":
        return set(FIXES)
    if variant.startswith("all-"):
        return set(FIXES) - {variant[4:]}
    return set(variant.split("+"))


def prompt(on: set[str]) -> str:
    p = system_prompt("baseline")
    if "json" not in on:
        props = answer_json_schema()["properties"]
        lines = [f"- `{k}`: {v['description']}" + (f" (one of: {', '.join(v['enum'])})" if "enum" in v else "")
                 for k, v in props.items()]
        p += REPLY_FORMAT.format(fields="\n".join(lines))
    if "instructions" in on:
        p += INSTRUCTIONS
    return p


def _json(text: str):
    t = (text or "").strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    return json.loads(m.group(1) if m else t)


def validation_error(text: str) -> str | None:
    """None when the reply parses into CheckedAnswer, else the message a retry sends back."""
    try:
        CheckedAnswer.model_validate(_json(text))
    except json.JSONDecodeError as e:
        return f"the reply is not JSON ({e.msg} at character {e.pos})"
    except ValidationError as e:
        return "; ".join(f"{'.'.join(map(str, x['loc'])) or 'reply'}: {x['msg'].removeprefix('Value error, ')}"
                         for x in e.errors())
    return None


def repaired(text: str, on: set[str] | None = None) -> tuple[str, list[dict]]:
    """The reply with its sql field post-processed by the fixes in `on` (repair, or cut and/or rewrite).
    Unchanged when the reply is not a JSON object with a string sql."""
    on = {"repair"} if on is None else on
    try:
        data = _json(text)
    except json.JSONDecodeError:
        return text, []
    if not isinstance(data, dict) or not isinstance(data.get("sql"), str):
        return text, []
    sql, changes = data["sql"], []
    steps = [repair] if "repair" in on else [f for k, f in (("cut", cut_first_statement), ("rewrite", rewrite)) if k in on]
    for step in steps:
        sql, ch = step(sql)
        changes += ch
    return (json.dumps(dict(data, sql=sql)) if changes else text), changes


def ask(provider: str, model: str, question: str, variant: str) -> dict:
    on = fixes(variant)
    system = prompt(on)
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": question}]
    first = call_model(provider, model, question, "baseline", messages=msgs, use_schema="json" in on)
    out = dict(first, variant=variant, fixes=sorted(on), validator_retries=0, validation_error=None,
               first_text=first["text"], repairs=[], second_error=None)
    if first["error"]:
        return out
    text = first["text"]
    post = on & {"repair", "cut", "rewrite"}
    if post:
        text, ch = repaired(text, post)
        out["repairs"] += ch
    if "pydantic" in on:
        err = validation_error(text)
        if err is not None:
            msgs += [{"role": "assistant", "content": first["text"]},
                     {"role": "user", "content": RETRY_PROMPT.format(error=err)}]
            second = call_model(provider, model, question, "baseline", messages=msgs, use_schema="json" in on)
            out.update(validator_retries=1, validation_error=err, second_text=second["text"])
            for k in ("tokens_in", "tokens_out", "tokens_cached", "tokens_reasoning"):
                out[k] = (first[k] or 0) + (second[k] or 0)
            out["latency_s"] = round((first["latency_s"] or 0) + (second["latency_s"] or 0), 3)
            if second["error"]:
                out.update(error=second["error"])
                return out
            text = second["text"]
            if post:
                text, ch = repaired(text, post)
                out["repairs"] += [dict(c, after_retry=True) for c in ch]
            out["second_error"] = validation_error(text)
    out["text"] = text
    return out


@solver
def adherent_answer(provider: str, model: str, variant: str):
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
    fixes(variant)
    if provider != "fake":
        load_keys()
    return Task(
        dataset=dataset(ids),
        solver=adherent_answer(provider=provider, model=model, variant=variant),
        scorer=[s() for s in ALL_SCORERS],
        model=sdk_model(provider, model),
        metadata={"provider": provider, "model_id": model, "config": variant},
        name=f"sql_adherence_{variant}_{model.split('/')[-1]}",
    )
