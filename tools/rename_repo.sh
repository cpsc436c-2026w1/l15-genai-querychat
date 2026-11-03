#!/usr/bin/env bash
# Rename the repo in every link and title: bash tools/rename_repo.sh <new-name> [org]
# Then rebuild the reports (bash reports/build.sh) so docs/ carries the new links.
set -euo pipefail
NEW=${1:?usage: tools/rename_repo.sh <new-name> [org]}
ORG=${2:-cpsc436c-2026w1}
OLD=genai-querychat
FILES="README.md pyproject.toml reports/_quarto.yml reports/index.qmd"
sed -i.bak -e "s#github.io/$OLD/#github.io/$NEW/#g" -e "s#github.com/[A-Za-z0-9_-]*/$OLD#github.com/$ORG/$NEW#g" \
  -e "s#[A-Za-z0-9_-]*\.github\.io/$NEW/#$ORG.github.io/$NEW/#g" -e "1s/^# $OLD$/# $NEW/" -e "s/^name = \"$OLD\"/name = \"$NEW\"/" $FILES
for f in $FILES; do rm -f "$f.bak"; done
grep -rnE "(^|[^A-Za-z0-9_-])$OLD" $FILES | grep -v "$NEW" || echo "renamed to $ORG/$NEW (dashboard NAME default left as is: it names AWS resources, not the repo)"
