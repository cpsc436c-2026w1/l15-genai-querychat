"""Bundle the logs into docs/ for GitHub Pages and drop your local folder path from the bundle.

    uv run python evals/mystep/publish.py
"""
import re, subprocess, sys
from pathlib import Path

name = Path(__file__).resolve().parent.name          # mystep
out = Path("docs/logs") / name
subprocess.run(["inspect", "view", "bundle", "--log-dir", f"logs/{name}", "--output-dir", str(out), "--overwrite"], check=True)
index = out / "index.html"
text = re.sub(r'"abs_log_dir": "[^"]*"', '"abs_log_dir": "logs"', index.read_text())
index.write_text(text)
leaks = [str(p) for p in out.rglob("*") if p.is_file() and p.suffix in {".html", ".json"} and str(Path.cwd()) in p.read_text(errors="ignore")]
if leaks:
    sys.exit(f"local path still in: {leaks}")
print(f"published to {out}/ (open it with: python -m http.server -d {out})")

# numbers for report.qmd, from the newest log
from statistics import median
from inspect_ai.log import read_eval_log
log = read_eval_log(sorted(Path(f"logs/{name}").glob("*.eval"))[-1])
ss = log.samples or []
passed = sum(1 for x in ss if next(iter(x.scores.values())).value == "C")
lat = [x.metadata.get("latency_s") for x in ss if x.metadata.get("latency_s") is not None]
tin = sum(x.metadata.get("tokens_in", 0) for x in ss); tout = sum(x.metadata.get("tokens_out", 0) for x in ss)
print(f"for report.qmd: run {log.eval.created[:10]}, n = {len(ss)}, passed {passed} of {len(ss)}, "
      f"median latency {median(lat):.2f} s, tokens {tin} in / {tout} out "
      f"(price of the run = tokens x your provider's price per token; OpenAI: https://openai.com/api/pricing)" if lat else "")
