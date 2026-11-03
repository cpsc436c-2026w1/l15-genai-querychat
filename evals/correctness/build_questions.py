"""Twelve questions over the taxi table, easy to hard, each with a reference SQL and the value DuckDB returns.

    uv run python -m evals.correctness.build_questions   # recompute reference_value in questions.yml

questions.yml is the source: question, reference SQL, kind and tolerance per question. This script runs each
reference SQL on data/taxi.duckdb and writes the value back into the file.

Tolerance (relative): counts must match exactly (0); averages and percentages within 1% of the reference (0.01).
A percentage may come back as a fraction (0.148 for 14.8%): the checker accepts either form.
Q12 is ambiguous on purpose ("trip length": minutes or miles?); its reference reading is duration in
minutes, and the other reading's value is stored as `alt_value` so the trace can show what happened."""

from __future__ import annotations

from pathlib import Path

import duckdb
import yaml

from harness.db import DB, build as build_db

QUESTIONS_YML = Path(__file__).resolve().parent / "questions.yml"
HEADER = """\
# Correctness eval: question, reference SQL, tolerance. One entry per question.
#   kind: count | mean | percent        tolerance: relative, 0 = exact
#   reference_value (and alt_value) are written by: uv run python -m evals.correctness.build_questions
#   reading / alt_reading / alt_sql: only on an ambiguous question, to say which reading a model took
"""


def load(path: Path = QUESTIONS_YML) -> list[dict]:
    """Questions as dicts; `rel_tol` is the tolerance under the name the checks use."""
    return [dict(q, rel_tol=float(q["tolerance"])) for q in yaml.safe_load(path.read_text())]


def save(questions: list[dict], path: Path = QUESTIONS_YML) -> None:
    clean = [{k: v for k, v in q.items() if k != "rel_tol"} for q in questions]
    path.write_text(HEADER + "\n" + yaml.safe_dump(clean, sort_keys=False, allow_unicode=True, width=120))


def shown(value: float, kind: str) -> int | float:
    """The reference as the log shows it: counts as integers, other values to 4 significant digits, far inside the
    1% tolerance (the scores of the 2026-11-02 run are the same with these values)."""
    return int(round(value)) if kind == "count" else float(f"{value:.4g}")


def build(path: Path = QUESTIONS_YML) -> list[dict]:
    build_db()
    con = duckdb.connect(str(DB), read_only=True)  # references: our own SQL, plain connection
    out = []
    for q in load(path):
        (value,) = con.execute(q["sql"]).fetchone()
        q["reference_value"] = shown(float(value), q["kind"])
        if q.get("alt_sql"):
            q["alt_value"] = shown(float(con.execute(q["alt_sql"]).fetchone()[0]), q["kind"])
        out.append(q)
    con.close()
    save(out, path)
    return out


if __name__ == "__main__":
    for r in build():
        print(f"{r['id']}  {r['level']:9s} {r['reference_value']:>14,.4f}  {r['question']}")
