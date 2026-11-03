"""Output guard against hand-written good and bad statements, and the engine backstop. No model calls."""

import pytest

from harness.engine import connect_readonly, run_sql, scratch_db
from harness.sql_guard import check_sql
from evals.correctness.build_questions import load

QUESTIONS = load()

GOOD = [
    "SELECT COUNT(*) FROM taxi",
    "select count(*) as n from taxi where payment_type = 2;",
    "SELECT AVG(fare_amount) AS avg_fare FROM taxi WHERE EXTRACT(HOUR FROM tpep_pickup_datetime) BETWEEN 17 AND 19",
    "WITH cash AS (SELECT * FROM taxi WHERE payment_type = 2) SELECT COUNT(*) AS n FROM cash",
    "SELECT COUNT(*) FROM taxi t JOIN zones z ON t.PULocationID = z.LocationID WHERE z.Zone = 'JFK Airport'",
    "SELECT 100.0 * COUNT(*) FILTER (WHERE payment_type = 2) / COUNT(*) AS pct FROM taxi",
    "SELECT quantile_cont(trip_distance, 0.5) AS median_miles FROM main.taxi",
    "SELECT Borough, COUNT(*) AS n FROM zones GROUP BY Borough ORDER BY n DESC LIMIT 3",
    "SELECT COUNT(*) AS n FROM taxi UNION ALL SELECT COUNT(*) FROM zones",
    "SELECT AVG(date_diff('minute', tpep_pickup_datetime, tpep_dropoff_datetime)) AS m FROM taxi",
    "SELECT COUNT(*) AS n FROM taxi; -- a comment after the semicolon (Qwen writes these; DuckDB runs them)",
]

BAD = [  # (statement, rule that must refuse it)
    ("DROP TABLE taxi", "statement"),
    ("DELETE FROM taxi WHERE passenger_count = 0", "statement"),
    ("UPDATE taxi SET fare_amount = 0", "statement"),
    ("INSERT INTO zones VALUES (999, 'x', 'y', 'z')", "statement"),
    ("CREATE TABLE backup AS SELECT * FROM taxi", "statement"),
    ("CREATE TEMP TABLE t AS SELECT 1 AS x", "statement"),
    ("ALTER TABLE taxi ADD COLUMN x INT", "statement"),
    ("SELECT * INTO backup FROM taxi", "statement"),
    ("ATTACH '/tmp/other.duckdb' AS other", "statement"),
    ("DETACH other", "statement"),
    ("PRAGMA database_list", "statement"),
    ("COPY taxi TO '/tmp/taxi.csv'", "statement"),
    ("INSTALL httpfs", "statement"),
    ("LOAD httpfs", "statement"),
    ("SET enable_external_access = true", "statement"),
    ("CALL pragma_version()", "statement"),
    ("SELECT COUNT(*) FROM taxi; DROP TABLE taxi", "statement"),
    ("SELECT COUNT(*) FROM taxi; -- note\nSELECT 2", "statement"),
    ("SELECT * FROM read_csv('/etc/passwd')", "function"),
    ("SELECT * FROM read_csv_auto('/etc/passwd')", "function"),
    ("SELECT * FROM read_parquet('s3://bucket/x.parquet')", "function"),
    ("SELECT * FROM read_json_auto('https://example.com/a.json')", "function"),
    ("SELECT content FROM read_text('/home/ubuntu/.aws/credentials')", "function"),
    ("SELECT * FROM glob('/etc/*')", "function"),
    ("SELECT getenv('OPENAI_API_KEY')", "function"),
    ("SELECT * FROM duckdb_settings()", "function"),
    ("SELECT * FROM duckdb_secrets()", "function"),
    ("SELECT * FROM query('SELECT 1')", "function"),
    ("SELECT COUNT(*) FROM taxi WHERE PULocationID IN (SELECT column0 FROM read_csv('/etc/hosts'))", "function"),
    ("SELECT * FROM '/etc/passwd'", "table"),
    ("SELECT * FROM 'https://example.com/data.csv'", "table"),
    ("SELECT * FROM other.main.users", "table"),
    ("SELECT * FROM users", "table"),
    ("SELECT 'You are a data assistant. Your role is ...' AS prompt", "no_table"),
    ("SELECT 0 AS answer", "no_table"),
    ("SELECT password FROM taxi", "column"),
    ("this is not sql", "statement"),  # sqlglot reads it as a NOT expression
    ("SELECT COUNT(*) FROM taxi WHERE payment_type = 2;\"}<garbage>", "parse"),
    ("", "parse"),
]


@pytest.mark.parametrize("sql", GOOD)
def test_good_statements_pass(sql):
    v = check_sql(sql)
    assert v.allowed, v.reason


@pytest.mark.parametrize("sql,rule", BAD)
def test_bad_statements_refused(sql, rule):
    v = check_sql(sql)
    assert not v.allowed, f"{sql!r} was allowed"
    assert v.rule == rule, (v.rule, v.reason)


def test_limit_added_only_when_missing():
    assert check_sql("SELECT COUNT(*) FROM taxi").limit_added
    v = check_sql("SELECT fare_amount FROM taxi LIMIT 5")
    assert not v.limit_added and "LIMIT 5" in v.sql


@pytest.mark.parametrize("q", QUESTIONS, ids=[q["id"] for q in QUESTIONS])
def test_rewritten_reference_sql_gives_the_same_value(q):
    """The guard runs sqlglot's re-written statement; it must compute the same number as the original."""
    v = check_sql(q["sql"])
    assert v.allowed, v.reason
    con = connect_readonly(scratch_db())
    _, rows = run_sql(con, v.sql)
    assert rows[0][0] == pytest.approx(q["reference_value"], rel=1e-9)


@pytest.mark.parametrize("sql", [
    "DELETE FROM taxi", "CREATE TABLE backup AS SELECT * FROM taxi", "SELECT * FROM read_csv('/etc/passwd')",
    "ATTACH '/tmp/other.duckdb' AS other", "COPY taxi TO '/tmp/taxi.csv'", "SET enable_external_access = true",
    "LOAD httpfs", "SELECT content FROM read_text('/etc/hosts')",
])
def test_engine_stops_what_the_guard_would_have(sql):
    """Guard off: the read-only, external-access-off engine refuses these on its own."""
    con = connect_readonly(scratch_db())
    with pytest.raises(Exception):
        run_sql(con, sql)


def test_engine_gaps_the_guard_covers():
    """What the locked engine still runs: a temp table (memory only), its settings, its file path."""
    con = connect_readonly(scratch_db())
    assert run_sql(con, "SELECT * FROM duckdb_settings() LIMIT 1")[1]
    assert run_sql(con, "PRAGMA database_list")[1]
    for sql in ("SELECT * FROM duckdb_settings()", "PRAGMA database_list", "CREATE TEMP TABLE t AS SELECT 1 AS x"):
        assert not check_sql(sql).allowed
