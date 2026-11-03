"""The DuckDB database the app and the evals run against: the taxi trips of January 2024 and the TLC zone lookup.

`build()` makes data/taxi.duckdb once from the two files that data/fetch.sh downloads (2.96 M trips, 265 zones). `connect()` opens it
read-only with external access off, so SQL written by a model can read the two tables and nothing else."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import duckdb

from harness import DATA

DB = DATA / "taxi.duckdb"
PARQUET = Path(os.environ.get("TAXI_PARQUET", DATA / "taxi_2024-01.parquet"))  # see data/README.md
ZONES = DATA / "taxi_zone_lookup.csv"

SQL_TIMEOUT_S = 30


def build(force: bool = False) -> Path:
    if DB.exists() and not force:
        return DB
    for f in (PARQUET, ZONES):
        if not f.exists():
            raise SystemExit(f"{f} is missing: run `bash data/fetch.sh` first")
    DB.unlink(missing_ok=True)
    con = duckdb.connect(str(DB))
    con.execute(f"CREATE TABLE taxi AS SELECT * FROM read_parquet('{PARQUET}')")
    con.execute(f"CREATE TABLE zones AS SELECT * FROM read_csv('{ZONES}', header=true)")
    con.close()
    return DB


_CON: duckdb.DuckDBPyConnection | None = None
_LOCK = threading.Lock()


def connect() -> duckdb.DuckDBPyConnection:
    """One locked-down read-only connection per process; callers take .cursor() for their own thread."""
    global _CON
    with _LOCK:
        if _CON is None:
            build()
            con = duckdb.connect(str(DB), read_only=True)
            con.execute("SET enable_external_access = false")
            con.execute("SET lock_configuration = true")
            _CON = con
    return _CON.cursor()


def run_sql(con: duckdb.DuckDBPyConnection, sql: str, timeout_s: int = SQL_TIMEOUT_S):
    """Run one SELECT; return (columns, rows). Raises on error or timeout."""
    timer = threading.Timer(timeout_s, con.interrupt)
    timer.start()
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(20)
    finally:
        timer.cancel()
    return cols, rows
