# Evaluate your own LLM step

[Inspect](https://inspect.aisi.org.uk/) is a Python tool that runs your step on a list of cases, scores each reply and saves everything in a log. You work in 2 places: your terminal, in the repo root, and your repo's page on github.com.

**1. Set up.** From your terminal, in the repo root:

```bash
uv sync                        # ends with "Installed N packages" (or "Checked N packages" on a rerun)
cp .env.example .env
```

Open `.env` in your editor and put your key after `OPENAI_API_KEY=`. Check it without printing it:

```bash
grep -c '^OPENAI_API_KEY=.' .env     # prints 1
```

**2. Copy the template and add your data.** From your terminal, in the repo root:

```bash
cp -r template evals/mystep
```

Put your table in `evals/mystep/table.csv`, with a header row. Any columns work: `call_step` sends the whole file to the model as text. For example:

```
product,price_usd,units_sold
oat milk,4.50,42
rye bread,6.00,17
```

**3. Write your cases** in `evals/mystep/samples.yml`, each with the answer you worked out yourself. `tolerance` is for numbers (0 = exact, 0.01 = within 1%). Text cases leave it out.

```yaml
- id: q01
  input: How many units of oat milk were sold?
  target: 42
  tolerance: 0
- id: q02
  input: Which product sold the most units?
  target: oat milk
```

Check that the file loads. From your terminal, in the repo root:

```bash
uv run python -c "import sys; sys.path.insert(0, 'evals/mystep'); from task import my_eval; print(len(my_eval().dataset), 'cases')"     # prints: 2 cases
```

**4. Connect your LLM step** in `evals/mystep/task.py`. `call_step(text)` gets one case's `input` as a string. It returns a dict whose `"output"` is the reply as a string, the text the scorer reads. Any other keys (`tokens_in`, `tokens_out`, `latency_s`) are kept in the log. On a failed call, let the exception raise: Inspect then marks the sample as an error and stops the run, so you fix the call instead of scoring it. Change `MODEL`, `PROMPT` and the body of `call_step`. Keep its name and its return value. Try one call (1 API call). From your terminal, in the repo root:

```bash
uv run python -c "import sys; sys.path.insert(0, 'evals/mystep'); from task import call_step; print(call_step('How many units of oat milk were sold?'))"
# prints a dict like: {'output': '42', 'tokens_in': 120, 'tokens_out': 2, 'latency_s': 0.8}
```

**5. Scoring.** `matches()` in `task.py` reads a number target as a number: it takes the first number in the reply ("42 units" reads as 42) and checks it against the tolerance. Any other target is compared as text, ignoring case, outer spaces, quotes and a final period, so "Oat milk." matches "oat milk" but "Oat milk is first" does not. Ask for the answer only in `PROMPT`, or write your own `@scorer` beside `matches()`.

**6. Run the eval.** An epoch is one pass over all your cases. From your terminal, in the repo root:

```bash
uv run inspect eval evals/mystep/task.py --log-dir logs/mystep --epochs 3
```

It ends with a `matches` accuracy and the log's file name under `logs/mystep/`. The header names `mockllm/model`, a placeholder: `call_step` calls the real model. If every sample completes, read a low accuracy as how your step behaves. If the run stops with an error, fix the setup or `call_step` first.

**7. Read the failures in the log viewer**, a local web page that shows every saved sample. From your terminal, in the repo root:

```bash
uv run inspect view --log-dir logs/mystep
```

Open <http://127.0.0.1:7575>. Click your run, then a sample scored I (incorrect). Read its input, the reply, the target and the score's explanation. Press Ctrl+C in the terminal when you are done.

**8. Write the report.** Fill in every `<...>` in `evals/mystep/report.qmd`: run date, model ids, n (cases x epochs), the step 6 command and your log URL from the table below. If you have [Quarto](https://quarto.org/docs/get-started/), render it. From your terminal, in the repo root:

```bash
quarto render evals/mystep/report.qmd -M embed-resources:true --output-dir "$PWD/docs/mystep"   # writes docs/mystep/report.html
```

**9. Publish.** From your terminal, in the repo root:

```bash
uv run python evals/mystep/publish.py      # prints: published to docs/logs/mystep/
git add evals/mystep docs
git commit -m "eval of my step"
git push
```

Then turn on GitHub Pages, on your repo's page on github.com:

1. Click **Settings**.
2. Click **Pages** in the left menu.
3. Under **Build and deployment**, set **Source** to **Deploy from a branch**.
4. Set the branch to **main** and the folder to **/docs**, then click **Save**.
5. Wait a minute, then reload the page: it shows your site's address at the top.

| you commit | stays on your laptop | your URLs |
|---|---|---|
| `evals/mystep/` (task, samples, table, report), `docs/logs/mystep/`, `docs/mystep/report.html` | `.env` (your key), `logs/mystep/` (the raw logs) | `https://<your-org>.github.io/<your-repo>/mystep/report.html` and `.../logs/mystep/` |
