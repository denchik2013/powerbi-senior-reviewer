# Evals

## 1. Triggering (does Claude pick this skill?)

Method: headless Claude Code sessions in a scratch git repo containing the `BadModel` PBIP plus one extra commit,
with the plugin loaded from this folder. File edits were disallowed, and each session was capped at a few turns. A prompt
"triggers" when the session's tool calls include `Skill` → `powerbi-senior-reviewer:powerbi-senior-reviewer`.

```bash
cd <scratch repo with a PBIP>
claude -p "<prompt>" --plugin-dir <this repo> --output-format stream-json --verbose \
       --max-turns 4 --disallowedTools "Edit,Write,NotebookEdit"
```

Results (2026-11-17, Claude Code default model):

| Prompt | Round 1 (first description) | Round 2 (revised description) |
|---|---|---|
| review my Power BI project | ✅ | ✅ |
| check this PBIP for problems | ✅ | – |
| is my DAX ok? | ✅ | ✅ ✅ (2/2 at 4 turns; 0/1 at a 2-turn cap, where it explored files first) |
| what best practices am I missing in my semantic model? | ✅ | – |
| look at …/Sales.tmdl and tell me what's wrong with it | ✅ | – |
| review this PR against main | ❌ picked the built-in `code-review` | ✅ |
| can you review my changes on this branch? | – | ✅ |
| review the diff of the last commit | – | ✅ ✅ (2/2 at 4 turns) |
| *control:* add a new page to the report with a bar chart | ✅ not triggered | ✅ not triggered |
| *control:* write a python function that reverses a string | ✅ not triggered | – |

Change between rounds: the description now leads with "Code review for Power BI. Reviews pull requests, branches,
commits and diffs…" and says to use it *instead of a generic code review* when the repo or diff contains PBIP/TMDL/PBIR
files. That fixed the PR collision with the built-in `code-review` skill.

## 2. Recall and false positives on fixtures

Planned for stage 4: see `tests/expected-issues.md`.
