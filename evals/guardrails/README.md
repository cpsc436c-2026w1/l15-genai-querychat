# evals/guardrails

The guardrail eval: attacks and real questions sent through the guarded runner in `harness/`, scored for what got
through to the user and for real questions blocked by mistake. The report page is
[guardrails.html](https://cpsc436c-2026w1.github.io/l15-genai-querychat/guardrails.html).

```bash
uv run python -m evals.guardrails.run_all --models gpt-5.4-nano   # nano only, the course key
uv run python -m evals.guardrails.run_all --report                 # results files from logs/guardrails, no model calls
```

| file | what it is |
|---|---|
| `redteam.yml` | 20 attacks, one entry per prompt: `kind`, the `attack` text, `expected` verdict, the `harm` check that decides a harmful outcome, and `env`, where an indirect injection is planted |
| `benign.yml` | the 12 real questions; their reference answers are in `../correctness/questions.yml` |
| `kb_poisoned_loud/`, `kb_poisoned_quiet/` | copies of the notebook's codebook with one planted chunk: an instruction written loudly, and the same claim written as a data note |
| `checks.py` | the scoring logic, no model calls: what counts as harm (`unsafe_sql`, `leak_prompt`, `leak_key`, `goal`, `answered`, `poisoned`) |
| `task.py` | the Inspect task: the dataset from the two YAML files, the runner from `harness/` as the solver, and the scorers `harmful`, `blocked`, `reached_execution`, `wrongly_blocked` |
| `run_all.py` | runs `task.py` on three models and four guard settings in one process, then writes `results/<date>-guardrails-inspect/` |
| `guard_eval.py` | the same eval as one script without Inspect, plus the indirect set: the poisoned schema value and the two poisoned chunks, with and without the context scan |

## Route

```
redteam.yml + benign.yml ─▶ task.py (one Sample per prompt) ─▶ harness Runner.run with the chosen guards
   ─▶ checks.py scorers ─▶ logs/guardrails ─▶ run_all.py --report ─▶ results/ ─▶ reports/guardrails.qmd
```

1. Read `redteam.yml`: each attack names the harm that would count against the app.
2. Read `checks.py` for how each harm is decided from the run's result.
3. Run one setting with Inspect, then open the log:
   `uv run inspect eval evals/guardrails/task.py -T model=gpt-5.4-nano -T guards=both -T input=rule --log-dir logs/guardrails`,
   then `uv run inspect view --log-dir logs/guardrails`.
4. Run all settings with `run_all.py`. The no-guard setting runs first, and the settings that send a model the same
   prompt share its one reply, so the differences between settings are the guards alone.

`guards` is `none`, `output` or `both`; `input` is `rule` or `classifier`. One run per prompt, guard setting and
model: the results are counts, not rates.
