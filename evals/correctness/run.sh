#!/usr/bin/env bash
# The whole correctness eval: tests, references, three models x 3 epochs, the one-line fix on Q12, the report.
# Keys come from .env or the environment (harness/keys.py) and are never printed. About US$0.15 of API calls.
#   bash evals/correctness/run.sh                 # from the repo root
#   EPOCHS=1 MODELS="openai gpt-5.4-nano" bash evals/correctness/run.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
export PYTHONPATH=.
EPOCHS="${EPOCHS:-3}"
LOGS=logs/correctness
uv run pytest -q
uv run python -m evals.correctness.build_questions
run() { uv run inspect eval evals/correctness/task.py -T provider="$1" -T model="$2" "${@:3}" \
          --epochs "$EPOCHS" --log-dir "$LOGS" --max-samples 4 --display plain; }
IFS=';' read -ra ms <<< "${MODELS:-groq qwen/qwen3.8-27b;openai gpt-5.4-nano;openai gpt-5.4-mini}"
for m in "${ms[@]}"; do run $m; done
for m in "${ms[@]}"; do run $m -T config=fixed -T ids=q12; done
uv run python -m evals.correctness.report --log-dir "$LOGS"
