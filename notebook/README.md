# notebook

The lecture notebook, `genai-intro-run.ipynb`, with its outputs: one analyst's question about the January 2024
taxi table, asked in plain words, from what the model is told to what one question costs. The stored outputs were
made with Qwen 3.8 27B on Groq (and all three models in Step F); the code calls GPT-5.4 nano, the model the course
key covers.

```bash
cd notebook && uv sync     # its own environment; it reads .env at the repo root
```

| file or step | what it is |
|---|---|
| `genai-intro-run.ipynb` | the notebook, steps below |
| `knowledge_base/taxi_glossary.txt` | the codebook as 6 paragraphs, one topic each: what the codes mean (payment types, rate codes) |
| `pyproject.toml`, `uv.lock` | the notebook's environment |
| Setup | loads the taxi table, the question "What is the average tip by payment type?" and a reference query |
| Step A | what querychat builds from the table: the system prompt, the tools, the schema tool's output, `data_description` and `extra_instructions` |
| Step B | the question end to end: each tool request, the result returned to the model, tokens per API call |
| Step C | format validation: `chat_structured` with a pydantic answer schema; the JFK flat-rate code that is in the codebook, not the table |
| Step D | a dashboard filter the model gets wrong: the update tool, which sends no rows to the provider, against the query tool, which does |
| Step E | codebook chunks retrieved (TF-IDF) for a question about cash tips, without and with the chunks in the user message |
| Step F | what one question costs on each model: prices per 1M tokens, the same question on each model, price per question |

## Route

```
table ─▶ querychat (system prompt, tools, schema) ─▶ question ─▶ tool calls ─▶ answer
                     Step A                          Step B         Step D     Step C
codebook chunks ─▶ user message (Step E)        tokens × prices ─▶ price per question (Step F)
```

Run the steps in order: each step uses the table and client set up before it. The guarded runner and the evals
that test the same app are in `../harness/` and `../evals/`.
