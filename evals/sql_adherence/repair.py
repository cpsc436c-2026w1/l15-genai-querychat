"""Post-processing in the tool: repair the model's SQL before it runs, and log every change.

    sql, changes = repair(sql)

Three steps, each logged as {"step", "before", "after"} only when it changes something:
  cut        keep the first statement: drop everything from the first semicolon on, and comments (-- and /* */)
  transpile  only when DuckDB cannot plan the cut statement: sqlglot reads the statement (DuckDB dialect, else its generic dialect) and writes it as DuckDB SQL.
             This quotes reserved words used as aliases, such as `do`
  columns    then, if it still does not plan, a column name that is not in taxi or zones and is close to one that is (difflib, ratio 0.85 or more,
             ignoring case) is replaced by it
A repair can change what a query means: the cut keeps a first statement that may not be the one the model meant,
and a near-miss column can be the wrong column. The report checks each repaired answer against the reference."""

from __future__ import annotations

import difflib
import re

import sqlglot
from sqlglot import exp

from evals.sql_adherence.validator import schema

_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)


def _cut(sql: str) -> str:
    s = _COMMENT.sub(" ", sql)
    s = s.split(";", 1)[0]
    return re.sub(r"\s+\n", "\n", s).strip()


def _transpile(sql: str) -> str:
    for read in ("duckdb", None):
        try:
            out = sqlglot.transpile(sql, read=read, write="duckdb")
        except sqlglot.errors.SqlglotError:
            continue
        if len(out) == 1:
            return out[0]
    return sql


def _columns(sql: str) -> tuple[str, list[tuple[str, str]]]:
    try:
        q = sqlglot.parse_one(sql, dialect="duckdb")
    except sqlglot.errors.SqlglotError:
        return sql, []
    known = {c for cols in schema().values() for c in cols}
    proper = {}
    from harness.db import connect
    for t in ("taxi", "zones"):
        for (name, *_r) in connect().execute(f"DESCRIBE {t}").fetchall():
            proper[name.lower()] = name
    aliases = {a.alias.lower() for a in q.find_all(exp.Alias)}
    swaps = []
    for col in q.find_all(exp.Column):
        n = col.name
        if not n or n.lower() in known or n.lower() in aliases:
            continue
        hit = difflib.get_close_matches(n.lower(), list(known), n=1, cutoff=0.85)
        if hit:
            swaps.append((n, proper[hit[0]]))
            col.set("this", exp.to_identifier(proper[hit[0]]))
    return (q.sql(dialect="duckdb") if swaps else sql), swaps


def _plans(sql: str) -> bool:
    from harness.db import connect
    try:
        connect().cursor().execute("EXPLAIN " + sql)
        return True
    except Exception:
        return False


def repair(sql: str) -> tuple[str, list[dict]]:
    """Cut always (when there is something after the first statement). Transpile and columns only when DuckDB
    cannot plan what is left, so a query that already runs is never rewritten."""
    changes = []
    s = _cut(sql)
    if s != sql.strip().rstrip(";").strip():
        changes.append(dict(step="cut", before=sql, after=s))
    if _plans(s):
        return s, changes
    t = _transpile(s)
    if t != s:
        changes.append(dict(step="transpile", before=s, after=t))
    if _plans(t):
        return t, changes
    c, swaps = _columns(t)
    if swaps:
        changes.append(dict(step="columns", before=t, after=c, swaps=swaps))
    return c, changes


# --- the two parts on their own: cut (safe, never rewrites) and rewrite (can change meaning) -------------------------

def cut_first_statement(sql: str) -> tuple[str, list[dict]]:
    """Keep the text up to the first semicolon that ends a complete statement, as written: nothing is rewritten.

    The boundary comes from sqlglot, not from a split on ";": a candidate cut is kept only when the text before it
    tokenizes (so the ";" is not inside a string literal or a quoted name) and parses as exactly one DuckDB
    statement. What follows the cut (stray JSON characters, comments, prose, a second query) is dropped."""
    text = sql.strip()
    for i, ch in enumerate(text):
        if ch != ";":
            continue
        head = text[:i].rstrip()
        try:
            stmts = [s for s in sqlglot.parse(head, dialect="duckdb") if s is not None]
        except sqlglot.errors.SqlglotError:
            continue
        if len(stmts) == 1:
            if text[i + 1:].strip():
                return head, [dict(step="cut", before=sql, after=head, dropped=text[i:])]
            return sql, []
    return sql, []


def rewrite(sql: str) -> tuple[str, list[dict]]:
    """sqlglot transpile, then near-miss column names, only when DuckDB cannot plan the SQL as it is."""
    if _plans(sql):
        return sql, []
    changes = []
    t = _transpile(sql)
    if t != sql:
        changes.append(dict(step="transpile", before=sql, after=t))
    if _plans(t):
        return t, changes
    c, swaps = _columns(t)
    if swaps:
        changes.append(dict(step="columns", before=t, after=c, swaps=swaps))
    return c, changes
