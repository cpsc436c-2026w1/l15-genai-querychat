"""Unit tests for sqlchecks.py on a small in-memory taxi table. Run: uv run --with pytest pytest -q tests"""

import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import sqlchecks  # noqa: E402


@pytest.fixture(scope="module")
def db():
    con = duckdb.connect()
    con.execute("CREATE TABLE taxi (trip_distance DOUBLE, payment_type BIGINT, fare_amount DOUBLE, store_and_fwd_flag VARCHAR)")
    con.execute("INSERT INTO taxi VALUES (25, 2, 90, 'N'), (1, 1, 8, 'Y')")
    return con, sqlchecks.schema_of(con)


def test_cut_drops_json_debris():
    sql, ch = sqlchecks.cut_first_statement('SELECT COUNT(*) AS cash_trips FROM taxi WHERE payment_type = 2;"}')
    assert sql == "SELECT COUNT(*) AS cash_trips FROM taxi WHERE payment_type = 2"
    assert ch[0]["dropped"] == ';"}'


def test_cut_keeps_semicolon_in_string_literal():
    q = "SELECT * FROM taxi WHERE store_and_fwd_flag = 'a;b'"
    assert sqlchecks.cut_first_statement(q) == (q, [])
    sql, ch = sqlchecks.cut_first_statement(q + "; -- trailing note")
    assert sql == q and ch[0]["dropped"] == "; -- trailing note"


def test_cut_leaves_single_statement_and_trailing_semicolon():
    assert sqlchecks.cut_first_statement("SELECT 1 FROM taxi;") == ("SELECT 1 FROM taxi;", [])
    assert sqlchecks.cut_first_statement("SELECT 1 FROM taxi") == ("SELECT 1 FROM taxi", [])


@pytest.mark.parametrize("sql, part", [
    ("SELECT 1 FROM taxi; SELECT 2 FROM taxi", "2 statements"),
    ("DELETE FROM taxi WHERE payment_type = 2", "DELETE statement"),
    ("SELECT tip_percent FROM taxi", "unknown column"),
    ("SELECT * FROM zones", "unknown table"),
    ("SELECT average(trip_distance) FROM taxi", "DuckDB cannot plan"),
])
def test_validator_rejects(db, sql, part):
    con, schema = db
    with pytest.raises(ValueError, match=part):
        sqlchecks.check_sql(sql, schema, con)


def test_validator_passes_real_queries(db):
    con, schema = db
    for q in ["SELECT * FROM taxi WHERE trip_distance > 20 AND payment_type = 2",
              "WITH t AS (SELECT payment_type, AVG(fare_amount) AS f FROM taxi GROUP BY 1) SELECT f FROM t",
              "SELECT COUNT(*) AS n FROM taxi;"]:
        assert sqlchecks.check_sql(q, schema, con) == q


def test_wrapper_off_is_untouched_and_on_cuts_and_rejects(db):
    con, schema = db
    calls, on = [], {"on": False}
    stats = sqlchecks.QuestionChecks()
    f = sqlchecks.wrap_sql_tool(lambda **kw: calls.append(kw) or "ran", enabled=lambda: on["on"], stats=stats,
                                tables=schema, con=con, make_error=lambda m: ("error", m))
    raw = {"table": "taxi", "query": 'SELECT * FROM taxi;"}', "title": "t"}
    assert f(**raw) == "ran" and calls[-1] == raw and not stats.cut_applied  # off: exactly the original call
    on["on"] = True
    assert f(**raw) == "ran" and calls[-1]["query"] == "SELECT * FROM taxi"
    assert stats.cut_applied and stats.cut_removed == ';"}'
    n = len(calls)
    out = f(table="taxi", query="SELECT tip_percent FROM taxi", title="t")
    assert out[0] == "error" and "unknown column" in out[1] and len(calls) == n
    assert len(stats.rejections) == 1
    stats.reset()
    assert not stats.cut_applied and stats.rejections == []
