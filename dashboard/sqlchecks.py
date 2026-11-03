"""SQL checks inside querychat's tools: cut, then validator, before DuckDB runs the model's SQL.

The one copy of the cut and the validator: the SQL adherence eval (evals/sql_adherence/repair.py and
validator.py) imports them from here, with the eval's database (tables taxi and zones). `check_sql` takes the
tables and the DuckDB connection as arguments, so the dashboard passes its own (one table, taxi).

  cut        keeps the text up to the first ";" that ends one complete DuckDB statement (sqlglot decides, so a ";"
             inside a string literal or a quoted name is not a boundary) and drops what follows. Nothing is rewritten.
  validator  one statement, a query (SELECT, WITH ... SELECT, UNION), tables that exist, columns that exist,
             then DuckDB's EXPLAIN. Its message goes back to the model as the tool's error, so the model can
             fix the SQL on its next turn (querychat's tool loop; no extra loop here).
"""

from __future__ import annotations

import time

import sqlglot
from sqlglot import exp


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


def schema_of(con, tables=("taxi",)) -> dict[str, set[str]]:
    return {t: {r[0].lower() for r in con.execute(f"DESCRIBE {t}").fetchall()} for t in tables}


def check_sql(sql: str, tables: dict[str, set[str]], con) -> str:
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
    names = " and ".join(sorted(tables))
    ctes = {c.alias_or_name.lower() for c in q.find_all(exp.CTE)}
    used = {t.name.lower() for t in q.find_all(exp.Table)}
    unknown_tables = used - set(tables) - ctes
    if unknown_tables:
        raise ValueError(f"unknown table(s) {sorted(unknown_tables)}: the tables are {names}")
    known = set().union(*(tables[t] for t in used & set(tables))) if used & set(tables) else set()
    aliases = {a.alias.lower() for a in q.find_all(exp.Alias)} | ctes
    for cte in q.find_all(exp.CTE):  # columns a CTE exposes
        aliases |= {s.alias_or_name.lower() for s in cte.this.selects} if isinstance(cte.this, exp.Query) else set()
    bad = sorted({c.name for c in q.find_all(exp.Column) if c.name and c.name.lower() not in known | aliases})
    if bad:
        raise ValueError(f"unknown column(s) {bad} for table(s) {sorted(used & set(tables))}")
    try:
        con.cursor().execute("EXPLAIN " + text)
    except Exception as e:
        raise ValueError(f"DuckDB cannot plan the query: {str(e).splitlines()[0][:200]}") from None
    return sql


class QuestionChecks:
    """What the checks did during one question; the trace item reads it."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.cut_applied = False
        self.cut_removed = ""
        self.rejections: list[str] = []
        self.calls: list[dict] = []  # one entry per tool call, in order: name, latency_s, check, cut_removed
        self.last_check: dict | None = None  # set by wrap_sql_tool, taken by wrap_timing for the same call


def wrap_sql_tool(func, *, enabled, stats: QuestionChecks, tables, con, make_error):
    """Wrap one querychat tool function (update_dashboard or query). enabled() False: the original, untouched.

    make_error(message) builds the tool result the model reads (querychat's own ContentToolResult with error)."""

    def wrapped(**kwargs):
        if not enabled() or "query" not in kwargs:
            stats.last_check = {"check": "off"}
            return func(**kwargs)
        sql, changes = cut_first_statement(kwargs["query"])
        info = {"check": "pass"}
        if changes:
            stats.cut_applied = True
            stats.cut_removed = (stats.cut_removed + changes[0]["dropped"])[:200]
            info["cut_removed"] = changes[0]["dropped"][:200]
        try:
            check_sql(sql, tables, con)
        except ValueError as e:
            msg = f"SQL check: {e}"
            stats.rejections.append(msg[:300])
            stats.last_check = {**info, "check": "reject"}
            return make_error(msg)
        stats.last_check = info
        return func(**{**kwargs, "query": sql})

    wrapped.__wrapped__ = func
    return wrapped


def wrap_timing(name, func, stats: QuestionChecks):
    """Time one tool call (any tool) and log it in order; takes the SQL check's verdict for the same call."""

    def timed(**kwargs):
        t0 = time.monotonic()
        stats.last_check = None
        try:
            return func(**kwargs)
        finally:
            entry = {"name": name, "latency_s": round(time.monotonic() - t0, 3)}
            if stats.last_check:
                entry.update(stats.last_check)
            stats.calls.append(entry)
            stats.last_check = None

    timed.__wrapped__ = func
    return timed
