# Evaluate your own LLM step

1. From the repo root: `uv sync`, then `cp .env.example .env` and add your `OPENAI_API_KEY`. Run every command below from the root.
2. Copy the template: `cp -r template evals/mystep`, and put your data in `evals/mystep/table.csv`.
3. Write your cases in `samples.yml`: a question, the answer you worked out yourself, and a tolerance for numbers.
4. In `task.py`, change `call_step` until it does what your app does (prompt, model, parsing). The example sends the table and the question to `gpt-5.4-nano`. The run header says `mockllm/model`: that is expected, because the model is called inside `call_step`.
5. Pick a scorer in `my_eval()`: `scorer=exact()` for text, `scorer=within_tolerance()` for numbers (the prompt must then ask for a number only), or write your own `@scorer`.
6. Run it: `uv run inspect eval evals/mystep/task.py --log-dir logs/mystep --epochs 3`.
7. Look at the samples: `uv run inspect view --log-dir logs/mystep` opens http://127.0.0.1:7575; stop it with Ctrl+C.
8. Publish them: `uv run inspect view bundle --log-dir logs/mystep --output-dir docs/logs/mystep`, then replace your local path in `docs/logs/mystep/index.html` (`"abs_log_dir"`) with `"logs"`. GitHub Pages serves `docs/` once you turn it on in the repo settings.
9. Fill in `report.qmd`: run date, model ids, n, the command above and a link to the logs.
