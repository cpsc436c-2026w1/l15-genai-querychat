"""Classify every SQL error of a correctness run: why the SQL the model wrote did not run. No model calls.

    uv run python -m evals.sql_adherence.diagnose [results/2026-11-02-correctness/samples.jsonl]

Each failing answer gets the first kind that fits, checked in this order (runaway output first when the reply
was cut off with a NUL byte):
  JSON punctuation      characters of the JSON reply leaked into the SQL string: "}, { or }, or a final period
  prose around the SQL  comments or sentences before or after the query (--, "Wait", "note", "RESPONSE")
  runaway output        the reply ran on until it was cut off (a NUL byte, or more than 3,000 characters)
  several statements    two or more queries in one string
  dialect or function   DuckDB does not know a word or function the SQL uses (a reserved alias, a missing function)
  wrong column name     DuckDB reports a column that does not exist
  non-SELECT            a statement that is not a query
  other                 anything else"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

from harness import ROOT

KINDS = ["JSON punctuation", "prose around the SQL", "runaway output", "several statements", "dialect or function",
         "wrong column name", "non-SELECT", "other"]
PROSE = re.compile(r"--|\b(wait|note|response|refined|corrected|clean sql|below)\b", re.I)


def kind(sql: str, error: str) -> str:
    s = (sql or "").strip()
    if "\x00" in s:  # cut off mid-token: what came before is noise, braces included
        return "runaway output"
    if re.search(r'["”]\s*}|[{}]', s):
        return "JSON punctuation"
    if PROSE.search(s):
        return "prose around the SQL"
    if s.endswith("."):
        return "JSON punctuation"
    if len(s) > 3000:
        return "runaway output"
    if re.search(r";\s*\S", s):
        return "several statements"
    if ("Catalog Error" in error and "Function" in error) or re.search(r'syntax error at or near "\w+"', error):
        return "dialect or function"
    if "Referenced column" in error or ("column" in error.lower() and "not found" in error.lower()):
        return "wrong column name"
    if "not a SELECT" in error:
        return "non-SELECT"
    return "other"


def diagnose(samples: Path) -> pd.DataFrame:
    s = pd.read_json(samples, lines=True, precise_float=True, dtype=False)
    e = s[s.outcome == "SQL error"].copy()
    e["kind"] = [kind(r.sql, r.sql_error or "") for r in e.itertuples()]
    return e


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "results" / "2026-11-02-correctness" / "samples.jsonl"
    e = diagnose(src)
    print(e.groupby(["model", "config", "kind"]).size().to_string())
