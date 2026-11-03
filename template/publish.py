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
sys.exit(f"local path still in: {leaks}") if leaks else print(f"published to {out}/ (open it with: python -m http.server -d {out})")
