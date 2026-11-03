"""Output guard on the model's SQL: parse it with sqlglot (DuckDB dialect) and allow one read-only query
over the two allowed tables, nothing else.

Rules, in the order they are checked (the first one that fails is the reason given):
  1. it parses, and it is exactly one statement
  2. the statement is a query: SELECT, WITH ... SELECT, or a set operation of SELECTs (UNION etc.)
     -> DDL, DML, PRAGMA, ATTACH/DETACH, COPY, INSTALL/LOAD, SET, CALL, SELECT ... INTO are refused
  3. no function from the deny list: anything that reads files or URLs (read_csv*, read_parquet, read_json*,
     read_text, read_blob, glob, ...), runs SQL from a string (query, query_table), or reads the engine's
     own settings, secrets, files or environment (duckdb_*, pragma_*, current_setting, getenv)
  4. every table is `taxi` or `zones` (optionally in schema `main`) or a CTE the query defines;
     no table functions, no file paths in FROM ('/etc/passwd' is a table name to the parser)
  5. it reads at least one allowed table (a literal-only SELECT carries no data answer; it is the channel
     a leaked prompt or an off-topic answer would come back through)
  6. every column is a column of taxi or zones, or an alias or CTE column the query defines
Then a LIMIT is added if the outer query has none.

This guard is the policy; the engine is the backstop. DuckDB is opened read-only with external access off
(see engine.py), so a statement this guard misses still cannot write the database or read a file."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

ALLOWED_TABLES = {
    "taxi": {"vendorid", "tpep_pickup_datetime", "tpep_dropoff_datetime", "passenger_count", "trip_distance",
             "ratecodeid", "store_and_fwd_flag", "pulocationid", "dolocationid", "payment_type", "fare_amount",
             "extra", "mta_tax", "tip_amount", "tolls_amount", "improvement_surcharge", "total_amount",
             "congestion_surcharge", "airport_fee"},
    "zones": {"locationid", "borough", "zone", "service_zone"},
}
DEFAULT_LIMIT = 100

# Function names (lower case) refused anywhere in the statement.
DENY_EXACT = {
    "glob", "sniff_csv", "parquet_scan", "parquet_metadata", "parquet_schema", "parquet_file_metadata",
    "parquet_kv_metadata", "query", "query_table", "getenv", "current_setting", "which_secret",
    "sqlite_scan", "sqlite_attach", "postgres_scan", "postgres_attach", "mysql_scan", "iceberg_scan",
    "delta_scan", "st_read", "http_get", "http_post", "load_aws_credentials", "checkpoint", "force_checkpoint",
}
DENY_PREFIX = ("read_", "duckdb_", "pragma_", "http", "httpfs", "s3", "gcs", "azure")
# sqlglot names some file readers with its own classes; catch them by class too.
DENY_CLASSES = tuple(c for c in (getattr(exp, n, None) for n in ("ReadCSV", "ReadParquet")) if c)
QUERY_TYPES = (exp.Select, exp.Union, exp.Intersect, exp.Except)


@dataclass
class SqlVerdict:
    allowed: bool
    reason: str | None = None   # why it was refused (None when allowed)
    rule: str | None = None     # which rule refused it: parse, statement, function, table, no_table, column
    sql: str | None = None      # the statement to run (LIMIT added), only when allowed
    limit_added: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _func_name(node: exp.Expression) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.this).lower()
    return (node.sql_name() or type(node).__name__).lower()


def _refuse(rule: str, reason: str) -> SqlVerdict:
    return SqlVerdict(False, reason, rule)


def check_sql(sql: str, allowed: dict[str, set[str]] = ALLOWED_TABLES, limit: int = DEFAULT_LIMIT) -> SqlVerdict:
    text = (sql or "").strip()
    if not text:
        return _refuse("parse", "empty SQL")
    try:
        statements = [s for s in sqlglot.parse(text, read="duckdb")
                      if s is not None and not isinstance(s, getattr(exp, "Semicolon", ()))]  # comment-only
    except SqlglotError as e:
        return _refuse("parse", f"does not parse as DuckDB SQL: {str(e).splitlines()[0][:160]}")
    if len(statements) != 1:
        return _refuse("statement", f"{len(statements)} statements; exactly one is allowed")
    tree = statements[0]

    if not isinstance(tree, QUERY_TYPES):
        kind = tree.key.upper() if not isinstance(tree, exp.Command) else str(tree.this).upper()
        return _refuse("statement", f"{kind} statement; only SELECT or WITH ... SELECT is allowed")
    if tree.find(exp.Into):
        return _refuse("statement", "SELECT ... INTO writes a table")
    for bad in (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter, exp.Command, exp.Set,
                exp.Pragma, exp.Copy):
        if tree.find(bad):
            return _refuse("statement", f"contains a {bad.__name__.upper()} statement")

    for f in tree.find_all(exp.Func):
        name = _func_name(f)
        if (DENY_CLASSES and isinstance(f, DENY_CLASSES)) or name in DENY_EXACT or name.startswith(DENY_PREFIX):
            return _refuse("function", f"function {name}() reads files, URLs, settings or runs SQL; not allowed")

    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    read_allowed = False
    for t in tree.find_all(exp.Table):
        if not isinstance(t.this, exp.Identifier):
            return _refuse("table", f"table function or expression in FROM ({t.this.sql(dialect='duckdb')[:60]})")
        name = t.name.lower()
        if t.args.get("catalog") or (t.db and t.db.lower() != "main"):
            return _refuse("table", f"table {t.sql(dialect='duckdb')} is outside the main schema")
        if name in allowed:
            read_allowed = True
        elif name not in cte_names:
            return _refuse("table", f"table {t.name!r} is not one of {sorted(allowed)}")
    if not read_allowed:
        return _refuse("no_table", "the query reads no allowed table (a literal-only SELECT is not a data answer)")

    known = set().union(*allowed.values())
    aliases = {a.alias.lower() for a in tree.find_all(exp.Alias)}
    for ta in tree.find_all(exp.TableAlias):
        aliases.add(ta.name.lower())
        aliases.update(c.name.lower() for c in ta.columns)
    aliases |= cte_names
    for c in tree.find_all(exp.Column):
        if c.name.lower() not in known | aliases:
            return _refuse("column", f"column {c.name!r} is not a column of the allowed tables")

    limit_added = False
    if not tree.args.get("limit"):
        tree = tree.limit(limit, copy=True) if isinstance(tree, exp.Select) else \
            exp.select("*").from_(tree.subquery("q")).limit(limit)
        limit_added = True
    return SqlVerdict(True, sql=tree.sql(dialect="duckdb"), limit_added=limit_added)


if __name__ == "__main__":
    import sys

    print(check_sql(" ".join(sys.argv[1:]) or "SELECT COUNT(*) FROM taxi").to_dict())
