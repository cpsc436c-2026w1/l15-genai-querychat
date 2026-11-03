"""The answer model with a validator on its SQL: Pydantic runs the checks below when the reply is parsed.

    CheckedAnswer.model_validate_json(reply_text)     # raises pydantic.ValidationError with the reason

The sql field must be:
  1. one statement that sqlglot parses in the DuckDB dialect,
  2. a query (SELECT, WITH ... SELECT, or a UNION of SELECTs), nothing that writes or configures,
  3. over the tables taxi and zones (or the query's own CTEs), with columns that exist in them,
  4. accepted by DuckDB's planner: EXPLAIN runs on the read-only database, so a missing function or a type error
     is caught without running the query.
A trailing semicolon is allowed, as the scorer strips it. The error text is what goes back to the model on a retry."""

from __future__ import annotations

import sqlglot
from pydantic import field_validator
from sqlglot import exp

from harness.db import connect
from harness.prompts import Answer

_SCHEMA: dict[str, set[str]] = {}


def schema() -> dict[str, set[str]]:
    if not _SCHEMA:
        con = connect()
        for t in ("taxi", "zones"):
            _SCHEMA[t] = {r[0].lower() for r in con.execute(f"DESCRIBE {t}").fetchall()}
    return _SCHEMA


def check_sql(sql: str) -> str:
    """Return the SQL unchanged, or raise ValueError with a message the model can act on."""
    text = sql.strip().rstrip(";").strip()
    try:
        statements = [s for s in sqlglot.parse(text, dialect="duckdb") if s is not None]
    except sqlglot.errors.SqlglotError as e:
        raise ValueError(f"the SQL does not parse as DuckDB: {str(e).splitlines()[0][:200]}") from None
    if len(statements) != 1:
        raise ValueError(f"the SQL holds {len(statements)} statements: send exactly one SELECT, with no comments "
                         "or text before or after it")
    q = statements[0]
    if not isinstance(q, exp.Query):
        raise ValueError(f"the SQL is a {q.key.upper()} statement: only one SELECT query is allowed")
    tables = schema()
    ctes = {c.alias_or_name.lower() for c in q.find_all(exp.CTE)}
    used = {t.name.lower() for t in q.find_all(exp.Table)}
    unknown_tables = used - set(tables) - ctes
    if unknown_tables:
        raise ValueError(f"unknown table(s) {sorted(unknown_tables)}: the tables are taxi and zones")
    known = set().union(*(tables[t] for t in used & set(tables))) if used & set(tables) else set()
    aliases = {a.alias.lower() for a in q.find_all(exp.Alias)} | {c.alias_or_name.lower() for c in q.find_all(exp.CTE)}
    for cte in q.find_all(exp.CTE):  # columns a CTE exposes
        aliases |= {s.alias_or_name.lower() for s in cte.this.selects} if isinstance(cte.this, exp.Query) else set()
    bad = sorted({c.name for c in q.find_all(exp.Column) if c.name and c.name.lower() not in known | aliases})
    if bad:
        raise ValueError(f"unknown column(s) {bad} for table(s) {sorted(used & set(tables))}")
    try:
        connect().cursor().execute("EXPLAIN " + text)
    except Exception as e:
        raise ValueError(f"DuckDB cannot plan the query: {str(e).splitlines()[0][:200]}") from None
    return sql


class CheckedAnswer(Answer):
    """The same four fields as Answer, with the SQL checked when the reply is parsed."""

    @field_validator("sql")
    @classmethod
    def sql_is_one_valid_select(cls, v: str) -> str:
        return check_sql(v)
