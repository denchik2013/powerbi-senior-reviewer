#!/bin/bash
# PR-mode eval scenario (see docs/EVALS.md §3). Usage: tests/eval/pr_scenario.sh <empty workdir>
# Calls Claude (costs tokens). Requires bash, git, python3, claude.
W=$1; REPO="$(cd "$(dirname "$0")/../.." && pwd)"
[ -n "$W" ] || { echo "usage: $0 <empty workdir>"; exit 2; }
[ ! -e "$W" ] || [ -z "$(ls -A "$W")" ] || { echo "$W is not empty"; exit 2; }
mkdir -p "$W" && cp -r "$REPO"/tests/fixtures/GoodModel $W/ && cp $REPO/.gitignore $W/ && cd $W
git init -q -b main && git add -A && git -c user.name=e -c user.email=e@e.invalid commit -qm base && git checkout -q -b feature/margin
python3 - <<'PY'
from pathlib import Path
import re
m=Path('GoodModel/GoodModel.SemanticModel/definition/tables/_Measures.tmdl'); s=m.read_text()
s=s.replace("measure Margin = [Sales Amount] - [Total Cost]","measure Margin = [Sales Amount] / [Total Cost]")
s=s.replace("\tcolumn Placeholder","\t/// Average net price per order line.\n\tmeasure 'Avg Line Value' = [Sales Amount] / [Order Lines]\n\t\tformatString: \\$#,0.00\n\t\tdisplayFolder: Sales\n\t\tlineageTag: 9e1a0000-0000-4000-8000-000000001199\n\n\tcolumn Placeholder")
m.write_text(s)
c=Path('GoodModel/GoodModel.SemanticModel/definition/tables/Customer.tmdl'); t=c.read_text()
t=re.sub(r"\tcolumn Segment\n(\t\t.*\n)+\n","",t); t=t.replace(', "Segment"}','}'); c.write_text(t)
PY
git -c user.name=e -c user.email=e@e.invalid commit -qam "Margin as ratio, avg line value, drop Segment"
mkdir -p out
claude -p "review my changes on this branch against main" --plugin-dir $REPO --output-format stream-json --verbose --max-turns 80 --permission-mode acceptEdits --allowedTools "Bash Read Write Edit Glob Grep Skill" > out/transcript.jsonl 2>&1
echo "== $W modified: $(git status --porcelain | wc -l) files: $(ls out | tr '\n' ' ')"
python3 -c "
import json
j=json.load(open('out/judgment.json')) if __import__('os').path.exists('out/judgment.json') else []
print('judgment ids:', [e['id'] for e in j if not e.get('dropped')])"
head -12 out/PR_COMMENT.md 2>/dev/null
