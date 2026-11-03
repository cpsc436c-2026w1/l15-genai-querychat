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

from pydantic import field_validator

from dashboard.sqlchecks import check_sql as _check_sql
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
    """Return the SQL unchanged, or raise ValueError with a message the model can act on.
    The checks are the dashboard's (dashboard/sqlchecks.py), run on the eval's tables and database."""
    return _check_sql(sql, schema(), connect())


class CheckedAnswer(Answer):
    """The same four fields as Answer, with the SQL checked when the reply is parsed."""

    @field_validator("sql")
    @classmethod
    def sql_is_one_valid_select(cls, v: str) -> str:
        return check_sql(v)
