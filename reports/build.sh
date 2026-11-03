#!/usr/bin/env bash
# Render the report pages to docs/ and bundle the Inspect logs into docs/logs/ (the log viewer, no server needed).
#   bash reports/build.sh        # from the repo root; logs/correctness and logs/guardrails must hold the .eval files
set -euo pipefail
cd "$(dirname "$0")/.."
uv run quarto render reports
for e in correctness guardrails; do
  if [ -d "logs/$e" ]; then
    uv run inspect view bundle --log-dir "logs/$e" --output-dir "docs/logs/$e" --overwrite
    # the bundle records the local folder it came from: keep only the relative name
    uv run python -c "import re,sys; p=sys.argv[1]; t=open(p).read(); open(p,'w').write(re.sub(r'\"abs_log_dir\": \"[^\"]*\"', '\"abs_log_dir\": \"logs\"', t))" "docs/logs/$e/index.html"
  fi
done
touch docs/.nojekyll
