"""Guarded text-to-SQL harness: question -> input guard -> model -> schema check -> output guard -> DuckDB -> answer.

The system prompt, the answer schema and the database live here too (prompts.py, db.py), so the two evals in
evals/ ask the model exactly what the harness asks it."""

from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
