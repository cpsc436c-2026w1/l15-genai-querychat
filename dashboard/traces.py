"""Per-question traces: one DynamoDB item per question, and one JSON line on stdout.

Optional: set TRACES_TABLE to the table's name to switch traces on. Unset, nothing is written or printed and the
password page says nothing about traces.

The item holds the question text (the password page says so), the SQL the model ran, whether it worked,
tokens, price and time. It holds no key, no password and no IP address. DynamoDB deletes it about
TRACE_TTL_DAYS days later by itself (TTL attribute expires_at). The stdout line has no question text and no SQL, so
CloudWatch Logs shows activity without the questions.

A failed write never breaks the answer: it is printed and the app carries on.
"""

from __future__ import annotations

import itertools
import json
import os
import threading
import time
from datetime import UTC, datetime

TABLE = os.environ.get("TRACES_TABLE", "")
ENABLED = bool(TABLE)
REGION = os.environ.get("TRACES_REGION") or os.environ.get("AWS_REGION") or "ca-central-1"
TTL_DAYS = int(os.environ.get("TRACE_TTL_DAYS", "7"))
SQL_TOOLS = ("querychat_update_dashboard", "querychat_query")

# USD per 1M tokens: (full-price input, cached input, output). List prices read 2026-11-02 from the Groq and
# OpenAI pricing pages (Standard tier), as on the Cost report page. Groq lists no cached price, so cached tokens
# are charged as full-price input.
PRICES = {
    "groq-qwen": (0.80, 0.80, 4.00),
    "openai-nano": (0.20, 0.02, 1.25),
    "openai-mini": (0.75, 0.075, 4.50),
}

_counter = itertools.count()
_client = None
_client_lock = threading.Lock()


def _dynamodb():
    global _client
    with _client_lock:
        if _client is None:
            import boto3

            _client = boto3.client("dynamodb", region_name=REGION)
        return _client


def cost_usd(model_key: str, tokens_in: int, tokens_cached: int, tokens_out: int) -> float:
    p_in, p_cached, p_out = PRICES[model_key]
    return (tokens_in * p_in + tokens_cached * p_cached + tokens_out * p_out) / 1e6


def summarize_turns(turns) -> dict:
    """Tokens, the last SQL and the outcome from the chat turns one question added."""
    tokens_in = tokens_cached = tokens_out = 0
    sql = None
    last_error = None  # error of the last SQL tool result, None when it worked
    for turn in turns:
        tok = getattr(turn, "tokens", None)
        if turn.role == "assistant" and tok:
            tokens_in += tok[0]
            tokens_out += tok[1]
            tokens_cached += tok[2]
        for c in turn.contents:
            ctype = getattr(c, "content_type", None)
            if ctype == "tool_request" and c.name in SQL_TOOLS:
                args = c.arguments if isinstance(c.arguments, dict) else {}
                sql = args.get("query", sql)
            elif ctype == "tool_result":
                req = getattr(c, "request", None)
                if req is None or req.name in SQL_TOOLS:
                    last_error = None if c.error is None else str(c.error)
    return {
        "sql": sql,
        "error": last_error,
        "tokens_in": tokens_in,
        "tokens_cached": tokens_cached,
        "tokens_out": tokens_out,
    }


def make_item(*, session_id, model_key, model_id, question, summary, error, latency_s, questions_left, now=None):
    now = time.time() if now is None else now
    ts = datetime.fromtimestamp(now, UTC).isoformat(timespec="milliseconds")
    err = error if error is not None else summary["error"]
    tin, tc, tout = summary["tokens_in"], summary["tokens_cached"], summary["tokens_out"]
    return {
        "session_id": session_id,
        "ts": f"{ts}#{next(_counter):06d}",
        "event": "question",
        "model": model_id,
        "question": question,
        "sql": summary["sql"],
        "ok": err is None,
        "error": err,
        "tokens_in": tin + tc,  # all input tokens, cached ones included
        "tokens_cached": tc,
        "tokens_out": tout,
        "cost_usd": round(cost_usd(model_key, tin, tc, tout), 6),
        "latency_s": round(latency_s, 2),
        "questions_left": questions_left,
        "expires_at": int(now) + TTL_DAYS * 86400,
    }


def make_event_item(*, session_id, event, questions_left, now=None):
    """A small item for a button press (reset_filters, reset_chat): no question, no model."""
    now = time.time() if now is None else now
    ts = datetime.fromtimestamp(now, UTC).isoformat(timespec="milliseconds")
    return {
        "session_id": session_id,
        "ts": f"{ts}#{next(_counter):06d}",
        "event": event,
        "questions_left": questions_left,
        "expires_at": int(now) + TTL_DAYS * 86400,
    }


def to_dynamodb(item: dict) -> dict:
    out = {}
    for k, v in item.items():
        if v is None:
            out[k] = {"NULL": True}
        elif isinstance(v, bool):
            out[k] = {"BOOL": v}
        elif isinstance(v, (int, float)):
            out[k] = {"N": repr(v)}
        else:
            out[k] = {"S": str(v)}
    return out


def summary_line(item: dict) -> str:
    """The stdout line: no question text, no SQL, no error text."""
    if item["event"] != "question":
        return json.dumps({k: item[k] for k in ("event", "session_id", "ts", "questions_left")})
    keep = ("event", "session_id", "ts", "model", "ok", "tokens_in", "tokens_out", "cost_usd", "latency_s",
            "questions_left")
    return json.dumps({**{k: item[k] for k in keep}, "error": item["error"] is not None})


def _put(item: dict, put) -> None:
    try:
        put(TableName=TABLE, Item=to_dynamodb(item))
    except Exception as e:  # noqa: BLE001 - a trace must never break the answer
        print(json.dumps({"event": "trace_write_failed", "ts": item["ts"], "error": f"{type(e).__name__}: {e}"[:300]}),
              flush=True)


def record(item: dict, put=None, background: bool = True) -> None:
    """Print the summary line and write the item, off the event loop unless background=False.
    Does nothing when traces are off (TRACES_TABLE unset) and no `put` is given."""
    if not ENABLED and put is None:
        return
    print(summary_line(item), flush=True)
    if put is None:
        try:
            put = _dynamodb().put_item
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"event": "trace_write_failed", "ts": item["ts"], "error": f"{type(e).__name__}: {e}"[:300]}),
                  flush=True)
            return
    if background:
        threading.Thread(target=_put, args=(item, put), daemon=True).start()
    else:
        _put(item, put)


async def traced(inner, done):
    """Pass an answer stream through, then call done(error), error None when the stream ended normally."""
    error = None
    try:
        async for chunk in inner:
            yield chunk
    except BaseException as e:
        error = f"{type(e).__name__}: {e}".rstrip(": ")[:500]
        raise
    finally:
        done(error)
