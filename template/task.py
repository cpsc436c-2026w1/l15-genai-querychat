"""One LLM step, evaluated with inspect_ai: dataset (samples.yml), solver (call_step), scorer.

    uv run inspect eval evals/mystep/task.py --log-dir logs/mystep --epochs 3

Same pattern as evals/correctness/task.py and evals/guardrails/task.py in this repo."""

from __future__ import annotations

import asyncio
from pathlib import Path

import yaml
from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, accuracy, scorer
from inspect_ai.solver import Generate, TaskState, solver

HERE = Path(__file__).resolve().parent


MODEL = "gpt-5.4-nano"                    # the model is chosen here, not with --model
PROMPT = "Answer from this table. Reply with the answer only.\n\n"
TABLE = HERE / "table.csv"                # your data, beside this file


def call_step(text: str) -> dict:
    """Your LLM step: send the question with your table to the model, return what your app returns."""
    from openai import OpenAI
    r = OpenAI().chat.completions.create(model=MODEL, messages=[
        {"role": "system", "content": PROMPT + TABLE.read_text()},
        {"role": "user", "content": text}])
    return {"output": r.choices[0].message.content.strip(),
            "tokens_in": r.usage.prompt_tokens, "tokens_out": r.usage.completion_tokens}


@solver
def my_step():
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        result = await asyncio.to_thread(call_step, state.input_text)
        state.metadata.update(result)                 # kept in the log: tokens, latency, anything you return
        state.output.completion = str(result.get("output", ""))
        return state
    return solve


@scorer(metrics=[accuracy()])
def exact():
    """The output equals the target, ignoring case and spaces around it."""
    async def score(state: TaskState, target: Target) -> Score:
        ok = state.output.completion.strip().lower() == target.text.strip().lower()
        return Score(value=CORRECT if ok else INCORRECT, answer=state.output.completion)
    return score


@scorer(metrics=[accuracy()])
def within_tolerance():
    """The output is a number within the case's relative tolerance of the target."""
    async def score(state: TaskState, target: Target) -> Score:
        try:
            got, want = float(state.output.completion), float(target.text)
        except ValueError:
            return Score(value=INCORRECT, answer=state.output.completion, explanation="not a number")
        tol = float(state.metadata.get("tolerance", 0))
        ok = abs(got - want) <= tol * abs(want) if tol else got == want
        return Score(value=CORRECT if ok else INCORRECT, answer=str(got), explanation=f"target {want}, tolerance {tol}")
    return score


@task
def my_eval() -> Task:
    cases = yaml.safe_load((HERE / "samples.yml").read_text())
    dataset = MemoryDataset([Sample(id=c["id"], input=c["input"], target=str(c["target"]), metadata=c) for c in cases])
    return Task(dataset=dataset, solver=my_step(), scorer=exact(), model="mockllm/model")   # a placeholder: call_step calls the real model
