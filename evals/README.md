# evals

Two evals of the same app, both as [Inspect](https://inspect.aisi.org.uk/) tasks: a dataset, a solver that runs the
app, and scorers. Run them from the repo root.

| eval | dataset | solver | scorers | run |
|---|---|---|---|---|
| `correctness/` | `questions.yml`: question, reference SQL, tolerance | one model call through the JSON schema | `schema_valid`, `sql_runs`, `value_correct`, tokens, latency | `bash evals/correctness/run.sh` |
| `sql_adherence/` | the correctness questions | the correctness solver with fixes switched on by `-T variant=`: instructions, json, pydantic (validator and one retry), cut, rewrite | the correctness scorers | `bash evals/sql_adherence/run.sh` |
| `guardrails/` | `redteam.yml` (attacks) and `benign.yml` (real questions) | the guarded runner in `harness/` | `harmful`, `blocked`, `reached_execution`, `wrongly_blocked` | `uv run python -m evals.guardrails.run_all` |

The default runs call three models and need Groq and GPT-5.4 mini access. With the course key, which covers GPT-5.4
nano only, run nano alone:

```bash
EPOCHS=1 MODELS="openai gpt-5.4-nano" bash evals/correctness/run.sh
uv run python -m evals.guardrails.run_all --models gpt-5.4-nano
PYTHONPATH=. uv run inspect eval evals/sql_adherence/task.py -T provider=openai -T model=gpt-5.4-nano -T variant=baseline \
  --epochs 1 --log-dir logs/sql_adherence --display plain   # one variant; run.sh loops over all three models
```

Each scorer is deterministic: the value DuckDB returns for the model's SQL against the value of the reference SQL,
or the run's status against what the prompt is scored for. No model judges another model here.

One guard setting on one model: `uv run inspect eval evals/guardrails/task.py -T model=gpt-5.4-nano -T guards=both
-T input=classifier --log-dir logs/guardrails`. `guards` is `none`, `output` or `both`, `input` is `rule` or
`classifier`.

`guardrails/guard_eval.py` is the same guardrail eval as one script without Inspect. It also runs the
indirect-injection set: the 12 real questions on a database with a poisoned zone value, and four fare and tip
questions with a poisoned knowledge-base chunk.

Correctness is adapted from Daniel Chen, DSCI 532 (`slides/08e-evals_inspect.qmd`, `code/lecture06/evals`).
