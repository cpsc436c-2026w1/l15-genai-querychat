"""Classify every SQL error of a correctness run: why the SQL the model wrote did not run. No model calls.

    uv run python -m evals.sql_adherence.diagnose [results/2026-11-02-correctness/samples.jsonl]

Each failing answer gets one kind. The text after the first semicolon decides most of them:
  quoting or JSON punctuation       only stray characters after the query ("}, ",", {, a final period): the end of
                                    the JSON reply leaked into the sql string
  prose or markdown around the SQL  comments or sentences after (or around) the query (--, "Wait", "note", fences)
  wrong dialect                     sqlglot reads it as DuckDB SQL, DuckDB does not (a reserved word as an alias,
                                    a function DuckDB lacks)
  invented or misspelled columns    DuckDB reports a column that does not exist
  non-SELECT                        a statement that is not a query
  other (several statements)        a second query after the first
  other (runaway output)            the reply ran on until it was cut off (a NUL byte)
  other (invalid syntax)            anything else that does not parse"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

from harness import ROOT

KINDS = ["quoting or JSON punctuation", "prose or markdown around the SQL", "wrong dialect",
         "invented or misspelled columns", "non-SELECT", "other (several statements)", "other (runaway output)",
         "other (invalid syntax)"]
PROSE = re.compile(r"--|```|\b(wait|note|response|refined|corrected|clean|below|ensure|semicolon|done)\b", re.I)


def _parses(sql: str) -> bool:
    import sqlglot
    try:
        return len([s for s in sqlglot.parse(sql, dialect="duckdb") if s is not None]) == 1
    except sqlglot.errors.SqlglotError:
        return False


def kind(sql: str, error: str) -> str:
    s = (sql or "").strip()
    if "\x00" in s:
        return "other (runaway output)"
    i = s.find(";")
    if i >= 0 and s[i + 1:].strip():
        tail = s[i + 1:].strip()
        if not re.search(r"[A-Za-z0-9]", tail):
            return "quoting or JSON punctuation"
        if re.match(r"[\W_]*(select|with)\b", tail, re.I) and not PROSE.search(tail):
            return "other (several statements)"
        return "prose or markdown around the SQL"
    if PROSE.search(s):
        return "prose or markdown around the SQL"
    if s.endswith(".") or re.search(r'[{}]|"\s*}', s):
        return "quoting or JSON punctuation"
    if "Referenced column" in error or ("column" in error.lower() and "not found" in error.lower()):
        return "invented or misspelled columns"
    if "not a SELECT" in error:
        return "non-SELECT"
    if _parses(s.rstrip(";")):
        return "wrong dialect"
    return "other (invalid syntax)"


def diagnose(samples: Path) -> pd.DataFrame:
    s = pd.read_json(samples, lines=True, precise_float=True, dtype=False)
    e = s[s.outcome == "SQL error"].copy()
    e["kind"] = [kind(r.sql, r.sql_error or "") for r in e.itertuples()]
    return e


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "results" / "2026-11-02-correctness" / "samples.jsonl"
    e = diagnose(src)
    print(e.groupby(["model", "config", "kind"]).size().to_string())
