# harness

The guarded text-to-SQL runner that both evals and the notebook's guard section use. It asks the model exactly
what `evals/correctness/` asks it: the querychat-style system prompt and the `Answer` schema of `prompts.py`.

```python
from harness.runner import Runner, CONFIGS
r = Runner(model="gpt-5.4-nano")                 # key from .env or the environment
r.run("How many trips were paid in cash?", CONFIGS["classifier+output"])
r.last_trace                                     # one row per step of that run
```

| file | what it is |
|---|---|
| `runner.py` | `Runner.run(question, guards)`: the route below, `Result`, the guard settings in `CONFIGS`, trace rows |
| `prompts.py` | the system prompt built from the database, the `Answer` schema, `parse_answer` (the schema check) |
| `input_guard.py` | `rule_guard` (patterns and a scope allow-list), `classifier_guard` (gpt-5.4-nano), `scan_text` |
| `sql_guard.py` | `check_sql`: the output guard |
| `engine.py` | scratch copies of the database (clean and poisoned), the locked read-only connection |
| `db.py` | builds `data/taxi.duckdb` from the TLC files |
| `context.py` | retrieval over the notebook's knowledge base, the poisoned copies for the guardrail eval |
| `llm.py` | one chat completion with a strict JSON schema (OpenAI SDK, Groq is OpenAI-compatible), list prices |
| `keys.py` | reads `GROQ_API_KEY` and `OPENAI_API_KEY` from the environment or `.env`, never prints them |
| `tests/` | the output guard on good and bad statements, the engine backstop, the runner with a fake model |

## Route

```
question ─▶ input guard ─▶ model ─▶ schema check ─▶ output guard ─▶ DuckDB ─▶ answer
```

**Input rule.** Regular expressions for known attack phrasings (instruction override, system-prompt extraction,
secrets, destructive SQL words, file or network access), then a scope allow-list: a question that names nothing in
the taxi data is off-topic. It takes microseconds and costs nothing. It misses every paraphrase it has no pattern
for, and a harmless question with a trigger word in it is blocked.

**Input classifier.** gpt-5.4-nano with a short prompt that names the app's one job and six block categories, and
the user's message fenced as data. It reads intent, so it catches paraphrases. It adds one API call and its delay
before the real model starts, and an API error blocks the question. It is a model too: its verdict on the same
prompt can change between calls.

**Schema check.** The reply must validate against `Answer`. On a failure the validation error goes back to the
model once. A second failure ends the run with `schema_failure`.

**Output guard.** sqlglot parses the model's SQL (DuckDB dialect). It must be one query that reads `taxi` or
`zones`. Statements that change anything, functions that read files or URLs, and functions that read the engine's
settings are refused. A LIMIT is added when there is none. DuckDB runs the statement sqlglot wrote back, so it runs
exactly what was checked. The guard does not read the `interpretation` field, and it cannot tell whether a valid
query answers the question.

**Engine.** DuckDB is opened read-only with external access off and the configuration locked. With every guard off
it still refuses writes, files, URLs and extension loads (`tests/test_sql_guard.py`). The guard is the policy you
can explain. The engine is the part that holds when the guard misses.

**Context scan.** The rule's patterns also run over what enters the prompt from the data: category values listed
in the schema and retrieved chunks. It catches an instruction written loudly and misses the same claim written as
a data note.

Book framing: Huyen, *AI Engineering*, ch. 5 "Defensive Prompt Engineering" (the attacks and the defenses) and
ch. 10 "Step 2. Put in Guardrails" and "Monitoring and Observability" (input and output guardrails, the trace).
