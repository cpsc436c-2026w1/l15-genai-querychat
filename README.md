# l15-genai-querychat

Ask a table a question in plain words. A language model writes the SQL, guards check the question and the query,
and DuckDB, a SQL engine that runs inside the Python process, computes the answer. The table is a month of New York
yellow taxi trips (January 2024, about 3 million trips). This repo holds the lecture notebook, the app's guarded
runner, two evals of it and their results.

**Reports:** <https://cpsc436c-2026w1.github.io/l15-genai-querychat/> (correctness, guardrails and cost, and the log
viewer of [Inspect](https://inspect.aisi.org.uk/), the eval tool used here, with every saved sample of every run).

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
| `evals/correctness/` | correctness cases: `questions.yml` (question, reference SQL, tolerance), the scorers and the Inspect task |
| `evals/guardrails/` | attacks and real questions: `redteam.yml` (attack, kind, expected verdict), `benign.yml`, the Inspect task |
| `results/` | raw results per run, dated, as JSON Lines. See `results/README.md` |
| `reports/` | Quarto sources of the report pages, rendered to `docs/` for GitHub Pages |
| `template/` | copy it to evaluate your own LLM step the same way |
| `data/` | where the TLC files go (`bash data/fetch.sh`), with their sources |
| `dashboard/` | the chat dashboard as a container on AWS Fargate, with its deploy scripts. See `dashboard/README.md` |

## Run it yourself (optional)

The lecture needs no key: every output is already in the notebook and on the report pages. To run the code you
need [uv](https://docs.astral.sh/uv/). The setup, the data and the tests need no key.

From your terminal, in the repo root:

```bash
bash data/fetch.sh     # about 50 MB. Ends with: taxi_2024-01.parquet: OK and taxi_zone_lookup.csv: OK
uv sync                # ends with "Installed N packages" (or "Checked N packages" on a rerun)
uv run pytest -q       # no API calls. Ends with: 98 passed
```

Model calls need your own keys. Copy [`.env.example`](.env.example) to `.env` (gitignored: never commit it), open it in your
editor and put each key after its `=`. Check without printing a key: `grep -c '^OPENAI_API_KEY=.' .env` prints 1
(the same with `GROQ_API_KEY`).

With the course key, which covers GPT-5.4 nano only, run the nano-only rows of the table below:
`EPOCHS=1 MODELS="openai gpt-5.4-nano" bash evals/correctness/run.sh` and
`uv run python -m evals.guardrails.run_all --models gpt-5.4-nano`. The default three-model runs need Groq and mini
access. The notebook calls nano by default.

| command | keys it needs | price at list prices |
|---|---|---|
| one question, below | OpenAI | under US$0.001 |
| `bash evals/correctness/run.sh` (Qwen 3.8 27B on Groq, GPT-5.4 nano and mini on OpenAI) | Groq and OpenAI | about US$0.13 |
| `EPOCHS=1 MODELS="openai gpt-5.4-nano" bash evals/correctness/run.sh` | OpenAI | under US$0.01 |
| `uv run python -m evals.guardrails.run_all` (the same 3 models) | Groq and OpenAI | about US$0.09 |
| `uv run python -m evals.guardrails.run_all --models gpt-5.4-nano` | OpenAI (the classifier guard is GPT-5.4 nano too) | under US$0.02 |

From your terminal, in the repo root:

```bash
uv run python -c "from harness.runner import Runner, CONFIGS; print(Runner(model='gpt-5.4-nano').run('How many trips were paid in cash?', CONFIGS['rule+output']))"
# prints: status='answered' sql='SELECT COUNT(*) ... WHERE payment_type = 2' value=439191.0 unit='trips' ...

bash evals/correctness/run.sh                 # ends with a line like: total $0.1333 -> .../results/<today>-correctness
uv run python -m evals.guardrails.run_all     # ends with a line like: spent $0.0870 -> .../results/<today>-guardrails-inspect
bash reports/build.sh                         # ends with: View bundle 'docs/logs/guardrails' created
```

`reports/build.sh` writes the report pages to `docs/`. Open `docs/index.html` in your browser.

The notebook has its own environment: `cd notebook && uv sync`, then open `genai-intro-run.ipynb` with that kernel. It reads the same `.env` at the repo root.

## Credits

- Eval pattern and structured-output example: adapted from Daniel Chen, DSCI 532.
- Notebook: builds on DSCI 532 lectures 6 and 7 (querychat, the taxi apps, the retrieval demo).
- System prompt: follows querychat's `prompts/prompt.md`.
- Data: NYC Taxi and Limousine Commission, see `data/README.md`.
