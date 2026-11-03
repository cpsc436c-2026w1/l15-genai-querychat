# Results

Raw results, one folder per run, named by the run's date. Every number on the report pages is computed from
these files. JSON Lines: one record per line, read with `pandas.read_json(path, lines=True, precise_float=True)`.

## 2026-11-02-correctness-r2 and 2026-11-02-guardrails-inspect-r2

The same two evals run again later that day with the code that logs the model name and tokens for the log viewer,
the headline scorer first and rounded reference values. Same files as below. The report pages read these runs.

## 2026-11-02-correctness

The correctness eval: 12 questions x 3 models x 3 epochs, then question q12 again with one vocabulary line added
(`config: fixed`). Written by `uv run python -m evals.correctness.report` from the inspect_ai logs.

| file | one record per |
|---|---|
| `samples.jsonl` | model answer: question, the model's reply (`sql`, `unit`, `interpretation`, `confidence`), the value DuckDB returned, the outcome (pass, value mismatch, SQL error, schema failure), tokens, latency |
| `summary.jsonl` | model and config: pass rate, failures by gate, tokens, price at list prices, median latency |
| `per_question.jsonl` | question: passes out of 3 per model (baseline) |
| `failing_trace.md` | the question models fail most, with its prompt and each model's reply |

## 2026-11-02-guardrails-inspect

The guardrail eval as an Inspect task (`evals/guardrails/task.py`): 20 attacks and 12 real questions x 3 models x
4 guard settings, one run each. Written by `uv run python -m evals.guardrails.run_all`. The guardrails page reads it.

| file | one record per |
|---|---|
| `samples.jsonl` | prompt, setting and model: status, the four scores, harmful, guard and model latency and price |
| `summary.jsonl` | model and setting: the counts on the guardrails page |
| `trace.jsonl` | step of a run (input_guard, model, schema_check, output_guard, execute, result) |

## 2026-11-02-guardrails

An earlier run of the same eval with the stand-alone script `evals/guardrails/guard_eval.py`, which also runs the
indirect-injection set (poisoned data and knowledge base on the real questions). The guardrail eval: 20 attacks and 12 real questions x 3 models x 4 guard configurations, plus the indirect
injection runs. Written by `uv run python -m evals.guardrails.guard_eval run`.

| file | one record per |
|---|---|
| `guard_runs.jsonl` | prompt, configuration and model: status (answered, blocked_input, blocked_output, engine_refused, sql_error), harmful, reached_engine, guard and model latency and price |
| `trace.jsonl` | step of a run (input_guard, model, schema_check, output_guard, execute, result), joined to `guard_runs.jsonl` by `trace_id` |
| `summary.jsonl` | model and configuration: the counts on the guardrails page |
| `indirect.jsonl` | poisoned source, configuration and model |
| `rule_vs_classifier.jsonl` | prompt: the input rule's verdict and the classifier's three verdicts |
| `per_attack.jsonl` | attack: outcome per configuration per model |

## 2026-11-02-sql-adherence

Why the model's SQL fails to run, and what fixes it (`evals/sql_adherence/`). 15 variants x 3 models x 12 questions
x 3 epochs. Written by `uv run python -m evals.sql_adherence.diagnose` and `... .report`.

| file | one record per |
|---|---|
| `diagnosis.jsonl` | SQL error of the two correctness runs: its kind and what the cut-at-the-first-semicolon query returns |
| `samples.jsonl` | answer: outcome, the first reply, the validator's message, retries, every post-processing change |
| `summary.jsonl` | model and variant: SQL error rate, value-correct rate, retries, repairs, extra tokens, price, median latency |
| `repairs.jsonl` | answer the post-processing changed: SQL before and after, the value of each, the reference |
| `json_cut_offline.jsonl` | answer of the json variant with the cut applied afterwards to the same reply (no model call) |
| `captures.md` | the cases and tables the lecture slides show |

The json+pydantic runs were made under the earlier variant name `pydantic_schema`, with the same prompt, validator
and retry. Their logs were relabeled `json+pydantic`. A first no-schema `pydantic` run was discarded: its prompt did
not describe the four answer fields, so most replies failed the schema check for that reason alone. The runs here
describe the fields in the prompt whenever json is off.

## 2026-11-02-cost

| file | what it holds |
|---|---|
| `prices.jsonl` | list prices read 2026-11-02: the three models per 1M tokens, Fargate ARM vCPU-hour and GB-hour, a public IPv4 address per hour |
| `querychat_question.jsonl` | the notebook's section 6: one question through querychat on each model, tokens per model |
| `dashboard_task.jsonl` | the dashboard's task size and its caps |
