# Evaluate your own LLM step

1. Copy this folder into your project: `cp -r template evals/mystep`.
2. Write your cases in `samples.yml`: an input and the expected output for each, plus any facts the scorer needs.
3. In `task.py`, make `call_step` call your LLM step (prompt, model, any parsing) and return what your app returns.
4. Pick a scorer in `task.py` (`exact` or `within_tolerance`) or write your own: it gets the output and the case.
5. Run it: `uv run inspect eval evals/mystep/task.py --log-dir logs/mystep --epochs 3`.
6. Look at the samples: `uv run inspect view --log-dir logs/mystep`.
7. Publish them: `uv run inspect view bundle --log-dir logs/mystep --output-dir docs/logs/mystep`.
8. Fill in `report.qmd`: run date, model ids, n, the command above and a link to the logs.
