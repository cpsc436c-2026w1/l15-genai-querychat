# genai-querychat

Ask a table a question in plain words. A language model writes the SQL, guards check the question and the query,
and DuckDB computes the answer. The table is a month of New York yellow taxi trips (January 2024, 2,964,624 trips).
This repo holds the lecture notebook, the app's guarded runner, two evals of it and their results.

**Reports:** <https://cpsc436c-2026w1.github.io/genai-querychat/> (correctness, guardrails, cost, and the Inspect
log viewer for every run). **Slides:** [generative AI lecture](DECK_URL).

## Route of one question

```
question ─▶ input guard ─▶ model ─▶ schema check ─▶ output guard ─▶ DuckDB ─▶ answer
            rule or          system    JSON schema,    one read-only    read-only,    sql, value (from DuckDB),
            classifier       prompt    one retry       SELECT over      no files or   unit, confidence,
                             + schema                  taxi and zones   network       interpretation
   every step ─▶ one trace row: question, verdicts, SQL, tokens, price, latency, model
```

The model never types the number. It writes a query, and the number the user sees is the one DuckDB returns.

| folder | what is in it |
|---|---|
| `notebook/` | the lecture notebook with its outputs (`genai-intro-run.ipynb`): querychat, tool calls, structured output, retrieval, price per question |
| `harness/` | the guarded runner (`runner.py`), its input, output and schema guards, the read-only engine and the trace. See `harness/README.md` |
| `evals/correctness/` | does it answer correctly? `questions.yml` (question, reference SQL, tolerance), the scorers and the Inspect task |
| `evals/guardrails/` | what gets through an attack? `redteam.yml` (attack, kind, expected verdict), `benign.yml`, the Inspect task |
| `results/` | raw results per run, dated, as JSON Lines. See `results/README.md` |
| `reports/` | Quarto sources of the report pages, rendered to `docs/` for GitHub Pages |
| `template/` | copy it to evaluate your own LLM step the same way |
| `data/` | where the TLC files go (`bash data/fetch.sh`), with their sources |
| `dashboard/` | the deployed chat dashboard |

## Run it yourself (optional)

The lecture needs no key: every output is already in the notebook and on the report pages. To run the code you
need [uv](https://docs.astral.sh/uv/) and a key for at least one provider. Groq and OpenAI both work. Each eval
below names its price at list prices.

```bash
cp .env.example .env              # put your own key(s) in .env (gitignored: never commit it)
bash data/fetch.sh                # the two TLC files, about 50 MB, checked by SHA-256
uv sync
uv run pytest -q                  # guards, scorers and runner against hand-made replies: no API calls

# one question through the guarded app
uv run python -c "from harness.runner import Runner, CONFIGS; print(Runner(model='gpt-5.4-nano').run('How many trips were paid in cash?', CONFIGS['rule+output']))"

# the evals (about US$0.13 and US$0.09 for all three models)
bash evals/correctness/run.sh
uv run python -m evals.guardrails.run_all
bash reports/build.sh             # report pages and log viewer into docs/
```

To try one model only: `EPOCHS=1 MODELS="openai gpt-5.4-nano" bash evals/correctness/run.sh`, or
`uv run python -m evals.guardrails.run_all --models gpt-5.4-nano`.

The notebook has its own environment: `cd notebook && uv sync`, then open `genai-intro-run.ipynb` with that kernel.

## Credits

The eval pattern (an Inspect task is a dataset, a solver and a scorer) and the structured-output example are
adapted from Daniel Chen, DSCI 532 (`slides/08e-evals_inspect.qmd`, `code/lecture06/evals`,
`code/lecture06/structured/01-simple.py`). The notebook builds on DSCI 532 lectures 6 and 7 (querychat, the taxi
apps, the retrieval demo). The system prompt follows querychat's `prompts/prompt.md`. Data: NYC Taxi and Limousine
Commission, see `data/README.md`.
