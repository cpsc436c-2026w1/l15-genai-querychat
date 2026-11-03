"""One guarded run of a question, start to finish, with a trace row per step.

    question -> input guard -> model (system prompt + schema) -> schema check (one retry) -> output guard
             -> DuckDB read-only -> answer {sql, value, unit, confidence, interpretation}

`Guards` says which guards are on. The four configurations the guard eval compares are in CONFIGS; `scan`
(the context scan of retrieved chunks and schema values) is an extra used in the indirect-injection runs.

Every step appends one JSON line to the trace file: trace id, step, question, model, config, verdict, SQL,
tokens in and out, cost, latency and retries (Huyen, AI Engineering, ch. 10 "Monitoring and Observability",
"Logs and traces": record each step of a request, how long it took and what it cost)."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from harness import HERE
from harness.context import rag_message, retrieve, system_prompt
from harness.engine import connect_readonly, engine_refusal, run_sql, scratch_db
from harness.input_guard import classifier_guard, rule_guard
from harness.llm import MODEL_PROVIDER, chat_json
from harness.sql_guard import check_sql

_TRACE_LOCK = threading.Lock()


@dataclass(frozen=True)
class Guards:
    input: Literal[None, "rule", "classifier"] = None
    output: bool = False
    scan: bool = False  # context scan: drop retrieved chunks / schema values that read as instructions

    @property
    def name(self) -> str:
        parts = ([f"input {self.input}"] if self.input else []) + (["output"] if self.output else []) + \
                (["context scan"] if self.scan else [])
        return " + ".join(parts) or "none"


CONFIGS = {
    "none": Guards(),
    "output": Guards(output=True),
    "rule+output": Guards(input="rule", output=True),
    "classifier+output": Guards(input="classifier", output=True),
}


class Result(BaseModel):
    """What the application returns. `value` is what DuckDB returned for `sql`, never a number the model typed."""

    status: Literal["answered", "blocked_input", "blocked_output", "engine_refused", "sql_error",
                    "model_refused", "schema_failure", "api_error"]
    sql: str | None = None
    value: float | str | None = None
    unit: str | None = None
    confidence: Literal["low", "medium", "high"] | None = None
    interpretation: str | None = None  # the model's; an app shows it only with an answered result
    message: str | None = None  # why it was blocked or failed
    retries: int = 0


class SchemaFailure(RuntimeError):
    """The reply failed the schema check twice (once after the validation error was sent back)."""


@dataclass
class Runner:
    model: str
    db_path: Path | None = None
    kb_dir: Path | None = None
    trace_path: Path = HERE / "logs" / "trace.jsonl"
    reply_cache: dict | None = None   # (model, messages) -> reply; the guard eval shares one reply across configs
    fake: dict | None = None          # provider "fake": user message -> reply text (or list of replies)
    label: str = ""                   # free text written into every trace row (e.g. the red-team case id)
    strict: bool = True               # raise SchemaFailure on a second schema failure
    _rows: list = field(default_factory=list, repr=False)

    def __post_init__(self):
        self.db_path = Path(self.db_path or scratch_db())
        self.trace_path = Path(self.trace_path)
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)

    # -- trace -------------------------------------------------------------------------------------------
    def _log(self, ctx: dict, step: str, **kw):
        row = dict(ts=round(time.time(), 3), trace_id=ctx["trace_id"], label=self.label, step=step,
                   question=ctx["question"], model=self.model, config=ctx["config"], verdict=None, detail=None,
                   sql=None, tokens_in=0, tokens_out=0, cost_usd=0.0, latency_s=0.0, retries=ctx["retries"])
        row.update(kw)
        self._rows.append(row)
        with _TRACE_LOCK, self.trace_path.open("a") as f:
            f.write(json.dumps(row, default=str) + "\n")

    # -- model ---------------------------------------------------------------------------------------------
    def _call(self, messages: list[dict]) -> dict:
        from harness.prompts import answer_json_schema

        provider = "fake" if self.fake is not None else MODEL_PROVIDER.get(self.model, "openai")
        key = hashlib.sha256(json.dumps([self.model, messages]).encode()).hexdigest()
        if self.reply_cache is not None and key in self.reply_cache:
            return dict(self.reply_cache[key], cached=True)
        r = chat_json(self.model, messages, answer_json_schema(), provider=provider, fake=self.fake)
        if self.reply_cache is not None and not r["error"]:
            self.reply_cache[key] = r
        return dict(r, cached=False)

    # -- run -----------------------------------------------------------------------------------------------
    def run(self, question: str, guards: Guards = CONFIGS["none"], config: str | None = None) -> Result:
        from harness.prompts import parse_answer

        ctx = dict(trace_id=uuid.uuid4().hex[:12], question=question, config=config or guards.name, retries=0)
        self._rows = []
        t_start = time.perf_counter()
        res = self._run(question, guards, ctx, parse_answer)
        tot = lambda k: sum(r[k] for r in self._rows)  # noqa: E731
        self._log(ctx, "result", verdict=res.status, detail=res.message, sql=res.sql,
                  tokens_in=tot("tokens_in"), tokens_out=tot("tokens_out"), cost_usd=tot("cost_usd"),
                  latency_s=round(time.perf_counter() - t_start, 3),
                  model_latency_s=round(sum(r["latency_s"] for r in self._rows if r["step"] == "model"), 3),
                  guard_latency_s=round(sum(r["latency_s"] for r in self._rows if r["step"].endswith("guard")), 4),
                  guard_cost_usd=sum(r["cost_usd"] for r in self._rows if r["step"].endswith("guard")),
                  answer=res.model_dump())
        if res.status == "schema_failure" and self.strict:
            raise SchemaFailure(res.message)
        return res

    def _run(self, question, guards, ctx, parse_answer) -> Result:
        # 1. input guard
        if guards.input:
            v = rule_guard(question) if guards.input == "rule" else classifier_guard(question)
            self._log(ctx, "input_guard", verdict="allow" if v.allowed else "block",
                      detail=f"{v.guard}: {v.category}: {v.reason}", tokens_in=v.tokens_in, tokens_out=v.tokens_out,
                      cost_usd=v.cost_usd, latency_s=v.latency_s)
            if not v.allowed:
                return Result(status="blocked_input", message=f"input guard ({v.guard}): {v.category}: {v.reason}")

        # 2. prompt: system prompt from the database, optional RAG context
        t0 = time.perf_counter()
        system, flagged = system_prompt(self.db_path, scan=guards.scan)
        user = question
        if self.kb_dir:
            chunks, rlog = retrieve(question, self.kb_dir, scan=guards.scan)
            user = rag_message(question, chunks)
            self._log(ctx, "retrieve", detail=rlog)
        if guards.scan:
            dropped = flagged + [f"chunk {r['chunk']}" for r in (rlog if self.kb_dir else []) if r["dropped"]]
            self._log(ctx, "context_guard", verdict="removed" if dropped else "clean", detail=dropped,
                      latency_s=round(time.perf_counter() - t0, 4))
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

        # 3. model, 4. schema check with one retry
        ans = None
        for attempt in (0, 1):
            ctx["retries"] = attempt
            r = self._call(messages)
            self._log(ctx, "model", verdict="error" if r["error"] else ("refusal" if r["refusal"] else "reply"),
                      detail=r["error"] or r["refusal"] or r["text"][:400], tokens_in=r["tokens_in"],
                      tokens_out=r["tokens_out"], cost_usd=r["cost_usd"], latency_s=r["latency_s"],
                      cached=r["cached"], rate_limited=r["rate_limited"])
            if r["error"]:
                return Result(status="api_error", message=r["error"], retries=attempt)
            if r["refusal"] and not r["text"]:
                return Result(status="model_refused", message=r["refusal"], retries=attempt)
            ans, err = parse_answer(r["text"])
            self._log(ctx, "schema_check", verdict="ok" if ans else "fail", detail=err)
            if ans:
                break
            if attempt == 0:
                messages = messages + [
                    {"role": "assistant", "content": r["text"]},
                    {"role": "user", "content": f"Your reply failed validation: {err}. Reply again with only the "
                                                "JSON object the response schema describes."}]
        if ans is None:
            return Result(status="schema_failure", message=f"schema check failed after one retry: {err}",
                          retries=ctx["retries"])
        base = dict(sql=ans.sql, unit=ans.unit, confidence=ans.confidence, interpretation=ans.interpretation,
                    retries=ctx["retries"])

        # 5. output guard on the SQL
        sql = ans.sql.strip().rstrip(";").strip()
        if guards.output:
            t0 = time.perf_counter()
            sv = check_sql(sql)
            self._log(ctx, "output_guard", verdict="allow" if sv.allowed else "block",
                      detail=sv.reason or ("LIMIT added" if sv.limit_added else None), sql=sv.sql or sql,
                      latency_s=round(time.perf_counter() - t0, 4))
            if not sv.allowed:
                return Result(status="blocked_output", message=f"output guard ({sv.rule}): {sv.reason}",
                              **base)
            sql = sv.sql

        # 6. DuckDB, read-only, external access off
        t0 = time.perf_counter()
        try:
            cols, rows = run_sql(connect_readonly(self.db_path), sql)
        except Exception as e:  # DuckDB parser, binder, permission and runtime errors
            msg = f"{type(e).__name__}: {str(e).splitlines()[0][:300]}"
            refused = engine_refusal(msg)
            self._log(ctx, "execute", verdict="engine_refused" if refused else "error", detail=msg, sql=sql,
                      latency_s=round(time.perf_counter() - t0, 4))
            return Result(status="engine_refused" if refused else "sql_error", message=msg,
                          **base)
        cell = rows[0][0] if rows and cols else None
        try:
            value = float(cell) if cell is not None else None
        except (TypeError, ValueError):
            value = str(cell)[:2000]
        self._log(ctx, "execute", verdict="ok", detail=f"{len(rows)} rows x {len(cols)} cols", sql=sql,
                  latency_s=round(time.perf_counter() - t0, 4))
        return Result(status="answered", value=value, **base)

    @property
    def last_trace(self) -> list[dict]:
        return list(self._rows)
