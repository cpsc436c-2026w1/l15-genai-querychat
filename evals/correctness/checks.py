"""Pure scoring logic, unit-tested in tests/ against hand-made answers (no model calls).

A model's reply goes through three gates in order; the first one it fails names the failure:
  1. schema   - the reply is JSON that validates against `Answer` (all fields, confidence in the enum)
  2. sql      - the SQL is a single SELECT/WITH statement and DuckDB runs it without error
  3. value    - the first cell of the result is a number within tolerance of the reference
Tolerance: counts exact; means and percentages within 1% relative. On percentage questions a fraction
(0.148 for 14.8%) also passes, because the unit field says which one the model meant."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from harness.db import connect, run_sql
from harness.prompts import parse_answer

_CON = None
_SQL_CACHE: dict[str, tuple] = {}


def _con():
    global _CON
    if _CON is None:
        _CON = connect()
    return _CON


@dataclass
class Verdict:
    schema_ok: bool = False
    schema_error: str | None = None
    sql_ok: bool = False
    sql_error: str | None = None
    value: float | None = None          # what DuckDB returned for the model's SQL
    result_shape: str | None = None     # rows x cols of the result (first 20 rows fetched)
    value_ok: bool = False
    value_note: str | None = None
    answer: dict = field(default_factory=dict)

    @property
    def outcome(self) -> str:
        if not self.schema_ok:
            return "schema failure"
        if not self.sql_ok:
            return "SQL error"
        if not self.value_ok:
            return "value mismatch"
        return "pass"

    def to_dict(self) -> dict:
        return asdict(self) | {"outcome": self.outcome}


_ONE_SELECT = re.compile(r"^\s*(--[^\n]*\n\s*)*(select|with)\b", re.I | re.S)


def sql_guard(sql: str) -> str | None:
    """Return a reason to refuse, or None. The database is read-only anyway; this enforces the prompt's rules."""
    s = sql.strip().rstrip(";").strip()
    if not _ONE_SELECT.match(s):
        return "not a SELECT/WITH statement"
    if ";" in re.sub(r"'(?:[^']|'')*'", "''", s):
        return "more than one statement"
    return None


def execute(sql: str):
    """(cols, rows) or raises. Cached per SQL text: three scorers and epochs share one run."""
    key = sql.strip().rstrip(";").strip()
    if key not in _SQL_CACHE:
        try:
            _SQL_CACHE[key] = ("ok", run_sql(_con().cursor(), key))
        except Exception as e:  # DuckDB binder/parser/runtime errors, interrupts
            _SQL_CACHE[key] = ("err", f"{type(e).__name__}: {str(e).splitlines()[0][:300]}")
    status, payload = _SQL_CACHE[key]
    if status == "err":
        raise RuntimeError(payload)
    return payload


def value_matches(value: float, reference: float, rel_tol: float, kind: str) -> tuple[bool, str]:
    candidates = [("as returned", value)]
    if kind == "percent":
        candidates.append(("fraction x 100", value * 100))
    for label, v in candidates:
        if rel_tol == 0:
            ok = round(v) == round(reference) and abs(v - round(v)) < 1e-9
        else:
            ok = abs(v - reference) <= rel_tol * abs(reference)
        if ok:
            return True, f"{v:,.4f} matches reference {reference:,.4f} ({label}, tol {rel_tol:.0%})"
    return False, f"{value:,.4f} vs reference {reference:,.4f} (tol {'exact' if rel_tol == 0 else f'{rel_tol:.0%}'})"


def judge(text: str, meta: dict) -> Verdict:
    v = Verdict()
    ans, err = parse_answer(text)
    if ans is None:
        v.schema_error = err
        return v
    v.schema_ok, v.answer = True, ans.model_dump()
    refuse = sql_guard(ans.sql)
    if refuse:
        v.sql_error = f"refused: {refuse}"
        return v
    try:
        cols, rows = execute(ans.sql)
    except RuntimeError as e:
        v.sql_error = str(e)
        return v
    v.sql_ok = True
    v.result_shape = f"{len(rows)}{'+' if len(rows) == 20 else ''} rows x {len(cols)} cols"
    if not rows or not cols:
        v.value_note = "query returned no rows"
        return v
    cell = rows[0][0]
    try:
        v.value = float(cell)
    except (TypeError, ValueError):
        v.value_note = f"first cell is not a number: {cell!r}"
        return v
    v.value_ok, v.value_note = value_matches(v.value, meta["reference_value"], meta["rel_tol"], meta["kind"])
    if len(rows) > 1 or len(cols) > 1:
        v.value_note += f"; result was {v.result_shape}, first cell used"
    if not v.value_ok and meta.get("alt_value") is not None:
        alt_ok, _ = value_matches(v.value, meta["alt_value"], meta["rel_tol"], meta["kind"])
        if alt_ok:
            v.value_note += f"; it matches the other reading ({meta['alt_reading']}: {meta['alt_value']:,.4f})"
    return v
