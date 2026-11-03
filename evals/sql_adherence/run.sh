#!/usr/bin/env bash
# The SQL adherence ablation: 10 variants x 3 models x 12 questions x 3 epochs, then the results files.
# Keys from .env or the environment. About US$0.95 at list prices.
#   bash evals/sql_adherence/run.sh            # from the repo root
set -euo pipefail
cd "$(dirname "$0")/../.."
export PYTHONPATH=.
for v in baseline instructions json pydantic repair all all-instructions all-json all-pydantic all-repair; do
  for m in "groq qwen/qwen3.8-27b" "openai gpt-5.4-nano" "openai gpt-5.4-mini"; do
    set -- $m
    uv run inspect eval evals/sql_adherence/task.py -T provider="$1" -T model="$2" -T variant="$v" \
      --epochs 3 --log-dir logs/sql_adherence --max-samples 4 --display plain
  done
done
uv run python -m evals.sql_adherence.diagnose
uv run python -m evals.sql_adherence.report
