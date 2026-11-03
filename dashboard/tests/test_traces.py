"""Unit tests for traces.py with the DynamoDB call faked. Run: uv run --with pytest pytest -q tests"""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from chatlas import AssistantTurn, UserTurn
from chatlas.types import ContentToolRequest, ContentToolResult

os.environ.setdefault("TRACES_TABLE", "test-traces")  # traces on for these tests
sys.path.insert(0, str(Path(__file__).parent.parent))
import traces  # noqa: E402

SQL = "SELECT * FROM taxi WHERE trip_distance > 20 AND payment_type = 2"


def question_turns(error=None):
    req = ContentToolRequest(id="t1", name="querychat_update_dashboard",
                             arguments={"table": "taxi", "query": SQL, "title": "Trips"})
    res = ContentToolResult(value="ok" if error is None else "failed", request=req,
                            error=None if error is None else Exception(error))
    return [
        UserTurn("Filter the table to trips longer than 20 miles paid in cash"),
        AssistantTurn([req], tokens=(1000, 100, 9000)),
        UserTurn([res]),
        AssistantTurn(["Done."], tokens=(60, 20, 10000)),
    ]


def item_for(turns, error=None):
    return traces.make_item(session_id="s1", model_key="openai-nano", model_id="gpt-5.4-nano",
                            question="Filter the table to trips longer than 20 miles paid in cash",
                            summary=traces.summarize_turns(turns), error=error, latency_s=3.14159,
                            questions_left=14, now=1_793_700_000)


def test_success_item_fields_and_cost():
    it = item_for(question_turns())
    assert it["sql"] == SQL and it["ok"] is True and it["error"] is None
    assert it["tokens_in"] == 1060 + 19000 and it["tokens_cached"] == 19000 and it["tokens_out"] == 120
    # nano: 1,060 full-price x 0.20 + 19,000 cached x 0.02 + 120 out x 1.25, per 1M
    assert it["cost_usd"] == pytest.approx((1060 * 0.20 + 19000 * 0.02 + 120 * 1.25) / 1e6, abs=1e-6)
    assert it["expires_at"] == 1_793_700_000 + 7 * 86400
    assert it["latency_s"] == 3.14
    assert it["event"] == "question"
    assert set(it) == {"session_id", "ts", "event", "model", "question", "sql", "ok", "error", "tokens_in", "tokens_cached",
                       "tokens_out", "cost_usd", "latency_s", "questions_left", "expires_at"}


def test_ts_unique_and_sortable():
    a, b = item_for(question_turns()), item_for(question_turns())
    assert a["ts"] != b["ts"] and a["ts"] < b["ts"] and a["ts"].startswith("2026-")


def test_failed_tool_result_is_not_ok():
    it = item_for(question_turns(error="Permission Error: file system operations are disabled"))
    assert it["ok"] is False and "disabled" in it["error"]


def test_dynamodb_types_and_record_with_fake_put(capsys):
    calls = []
    it = item_for(question_turns(error="boom"))
    traces.record(it, put=lambda **kw: calls.append(kw), background=False)
    (call,) = calls
    assert call["TableName"] == traces.TABLE
    av = call["Item"]
    assert av["ok"] == {"BOOL": False} and av["error"] == {"S": "boom"} and av["sql"] == {"S": SQL}
    assert av["expires_at"] == {"N": str(1_793_700_000 + 7 * 86400)} and "S" in av["question"]
    line = json.loads(capsys.readouterr().out.strip())
    assert line["event"] == "question" and line["error"] is True
    assert "question" not in line and "sql" not in line and "taxi" not in json.dumps(line)


def test_null_sql_when_no_tool():
    it = item_for([UserTurn("hi"), AssistantTurn(["Hello"], tokens=(10, 5, 0))])
    assert it["sql"] is None and it["ok"] is True
    assert traces.to_dynamodb(it)["sql"] == {"NULL": True}


def test_failed_write_is_logged_not_raised(capsys):
    def put(**kw):
        raise RuntimeError("AccessDeniedException: not authorized")
    traces.record(item_for(question_turns()), put=put, background=False)
    out = capsys.readouterr().out.strip().splitlines()
    assert json.loads(out[-1])["event"] == "trace_write_failed"


def test_traced_stream_calls_done_on_success_and_on_error():
    seen = []

    async def ok():
        yield "a"
        yield "b"

    async def bad():
        yield "a"
        raise ValueError("model failed")

    async def run(gen):
        return [c async for c in traces.traced(gen, seen.append)]

    assert asyncio.run(run(ok())) == ["a", "b"] and seen == [None]
    with pytest.raises(ValueError):
        asyncio.run(run(bad()))
    assert seen[-1] == "ValueError: model failed"


def test_reset_item_is_small(capsys):
    calls = []
    it = traces.make_event_item(session_id="s1", event="reset_chat", questions_left=12, now=1_793_700_000)
    assert set(it) == {"session_id", "ts", "event", "questions_left", "expires_at"}
    traces.record(it, put=lambda **kw: calls.append(kw), background=False)
    assert calls[0]["Item"]["event"] == {"S": "reset_chat"}
    assert json.loads(capsys.readouterr().out.strip()) == {k: it[k] for k in ("event", "session_id", "ts", "questions_left")}


def test_off_when_table_unset(monkeypatch, capsys):
    monkeypatch.setattr(traces, "ENABLED", False)
    traces.record(item_for(question_turns()), background=False)
    assert capsys.readouterr().out == ""
