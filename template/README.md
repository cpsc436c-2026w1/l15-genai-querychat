# Evaluate your own LLM step

1. From the repo root: `uv sync`, then `cp .env.example .env` and add your `OPENAI_API_KEY`. Run every command below from the root, Python included (`uv run python`).
2. Copy the template: `cp -r template evals/mystep`, and put your data in `evals/mystep/table.csv`.
3. Write your cases in `samples.yml`: a question, the answer you worked out yourself, and a tolerance for numbers. Start with a handful; add a case each time you find a new way the step fails.
4. In `task.py`, change `PROMPT` and `call_step` until they do what your app does. The example sends the table and the question to `gpt-5.4-nano`. The run header says `mockllm/model`: that is expected, because the model is called inside `call_step`.
5. The scorer `matches()` compares the first number in the reply with a number target (within the tolerance) and anything else as text, so the prompt should ask for the answer only. Write your own `@scorer` when that is not enough.
6. Run it: `uv run inspect eval evals/mystep/task.py --log-dir logs/mystep --epochs 3`. A low score is a finding about the step, not a setup error.
7. Look at the samples: `uv run inspect view --log-dir logs/mystep` opens http://127.0.0.1:7575; stop it with Ctrl+C.
8. Publish: `uv run python evals/mystep/publish.py` bundles the logs into `docs/logs/mystep/` and removes your local folder path. Commit `evals/mystep/` and `docs/logs/mystep/` (`logs/` stays local) and turn on GitHub Pages for `docs/`.
9. Fill in `report.qmd`: run date, model ids, n, the command above and the link to your published logs.
