"""inspect_ai scorers around checks.judge. Gates are scored independently (CORRECT / INCORRECT), and the
first failing gate is kept in metadata["outcome"] for the report. Tokens and latency are numeric scores."""

from __future__ import annotations

from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, accuracy, mean, scorer
from inspect_ai.solver import TaskState

from evals.correctness.checks import judge


def _verdict(state: TaskState):
    if state.store.get("error"):
        return None
    return judge(state.store.get("text") or "", state.metadata)


def _api_error(state):
    return Score(value=INCORRECT, explanation=f"API error: {state.store.get('error')}",
                 metadata={"outcome": "API error"})


@scorer(metrics=[accuracy()])
def schema_valid():
    """The reply is JSON matching the Answer schema."""
    async def score(state: TaskState, target: Target) -> Score:
        v = _verdict(state)
        if v is None:
            return _api_error(state)
        return Score(value=CORRECT if v.schema_ok else INCORRECT, answer=(state.store.get("text") or "")[:300],
                     explanation=v.schema_error or "valid", metadata=v.to_dict())
    return score


@scorer(metrics=[accuracy()])
def sql_runs():
    """The SQL is one SELECT and DuckDB runs it on the read-only database."""
    async def score(state: TaskState, target: Target) -> Score:
        v = _verdict(state)
        if v is None:
            return _api_error(state)
        if not v.schema_ok:
            return Score(value=INCORRECT, explanation="no SQL: schema failed", metadata=v.to_dict())
        return Score(value=CORRECT if v.sql_ok else INCORRECT, answer=v.answer["sql"],
                     explanation=v.sql_error or v.result_shape, metadata=v.to_dict())
    return score


@scorer(metrics=[accuracy()])
def value_correct():
    """The number DuckDB returns for the model's SQL matches the reference within tolerance."""
    async def score(state: TaskState, target: Target) -> Score:
        v = _verdict(state)
        if v is None:
            return _api_error(state)
        expl = v.value_note or v.sql_error or v.schema_error or ""
        return Score(value=CORRECT if v.value_ok else INCORRECT, answer=None if v.value is None else str(v.value),
                     explanation=expl, metadata=v.to_dict())
    return score


@scorer(metrics=[mean()])
def tokens():
    """Total tokens (in + out) the provider billed for this sample; the split is in metadata."""
    async def score(state: TaskState, target: Target) -> Score:
        s = state.store
        md = {k: s.get(k) or 0 for k in ("tokens_in", "tokens_out", "tokens_cached", "tokens_reasoning")}
        return Score(value=md["tokens_in"] + md["tokens_out"], metadata=md)
    return score


@scorer(metrics=[mean()])
def latency():
    """Wall-clock seconds for the API call (retries excluded: the last attempt is timed)."""
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=float(state.store.get("latency_s") or 0.0), metadata={"retries": state.store.get("retries")})
    return score


ALL_SCORERS = [value_correct, schema_valid, sql_runs, tokens, latency]  # first = the Score column of the run list
