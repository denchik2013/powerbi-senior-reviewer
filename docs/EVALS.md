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

**Ground truth:** [`tests/expected-issues.md`](../tests/expected-issues.md). BadModel has 43 planted issues: 36 static
(S, the scripts can find them; the reviewer must not drop them) and 7 judgment (J, only the reviewer can find them:
a measure whose logic contradicts its name, wrong averaging grain, a duplicate KPI, budget grain mismatch, RLS reach,
repeated sub-expressions, chart choice). GoodModel has none, so every kept finding counts as a false positive.

**Method:** `tests/eval/run_eval.py` copies a fixture into a fresh git repo (with this repo's `.gitignore`), runs
`claude -p "review my Power BI project" --plugin-dir <repo>` headless (edits allowed, so "did not modify the project" is
actually tested), then `tests/eval/grade.py` scores the run from `out/findings.json` + `out/judgment.json`:

- An issue is **found** when a kept finding has an accepted rule id (its own id, or one it cites, e.g. "per CUS009")
  **and** matches the issue's anchor regex. Static findings the reviewer marked `dropped` do not count.
- **Citations valid** means the cited file exists and the line lies inside it.
- **Fixture modified** comes from `git status` outside `out/`.

The grading is strict: a judgment finding that sits only in REVIEW.md prose, without an entry in `judgment.json`,
does not count.

**Baseline (scripts only, no Claude):** recall 36/43 = **84%** (S 100%, J 0%), GoodModel 0 findings.

### Round 1 (2026-11-18): first SKILL.md

| Run | Recall | S | J | Kept findings | Citations valid | Project modified | Missed |
|---|---|---|---|---|---|---|---|
| bad1 | 42/43 = 98% | 36/36 | 6/7 | 54 | 54/54 | no | B25 DAX104 |
| bad2 | 41/43 = 95% | 36/36 | 5/7 | 53 | 53/53 | no | B25 DAX104, B35 RPT103 |
| bad3 | 36/43 = 84% | 36/36 | 0/7 | 48 | 48/48 | no | all 7 J |
| good1 | – | – | – | **2** | 2/2 | no | – |
| good2 | – | – | – | **0** | – | no | – |

(Round-1 runs were re-graded with the final grader. The first grader also counted the runner's own transcript as a
project change; that bug is fixed.)

What we learned and changed:

1. **bad3 found the judgment issues but skipped the process.** Its REVIEW.md correctly called out Total Revenue,
   Avg Order Value, Budget vs Actual and DAX104, but it wrote no `judgment.json`, never re-scored, and cited lines as
   `Sales.tmdl:~15`. SKILL.md now requires `judgment.json` (even `[]`), a script-computed score, and exact line numbers.
2. **good1's two "false positives" were real defects in the GoodModel fixture.** A drill-through table showed
   `Customer[Email]` while the RLS role hid that column with OLS, so the visual breaks for those users. The same table
   also had a `[Customers]` measure that is always 1 per customer row. We fixed the fixture (dropped the unneeded
   personal-data column and the measure) instead of loosening the reviewer. The defects were good catches, and the
   GoodModel fixture now meets the bar it claims to.
3. **DAX104 (repeated sub-expression) was folded into the DAX002 fix** and never reported on its own. SKILL.md now says
   to report it separately.
4. **Merged findings.** Reviewers sometimes merge two issues into one finding ("SEC101 … per CUS009"). The grader
   accepts rule ids cited in the message.

### Round 2 (2026-11-18): final SKILL.md

| Run | Recall | S | J | Kept findings | Citations valid | Project modified | Missed |
|---|---|---|---|---|---|---|---|
| bad1 | 42/43 = **98%** | 36/36 | 6/7 | 54 | 54/54 | no | B35 RPT103 |
| bad2 | 42/43 = **98%** | 36/36 | 6/7 | 56 | 56/56 | no | B35 RPT103 |
| bad3 | 39/43 = **91%** | 33/36 | 6/7 | 48 | 48/48 | no | B04 DAX006, B08 SEC101, B39 DAX008, B41 MOD007 |
| good1 | – | – | – | **0** | – | no | – |
| good2 | – | – | – | **0** | – | no | – |
| good3 | – | – | – | **0** | – | no | – |

**Result: mean recall 96% (target ≥ 85%, every run met it), judgment recall 86% in every run, 0 false findings on
GoodModel in 3/3 runs (target ≤ 3), 100% valid citations, project never modified.** Each run took 1–1.5 minutes.

Notes on round 2:

- **bad3's misses were mostly deliberate merges, not blind spots.** DAX006 was merged into the DAX102 finding on the same
  measure (`Avg Order Value`). DAX008 was replaced by a sharper DAX102: `ALL(Sales)` leaves Product, Customer and Date
  slicers in the denominator. The RLS-reach issue (B08) is described inside the CUS009 finding ("the role filters only
  dim_store, so FactBudget…") without citing SEC101. Only the MOD007 drop ("superseded") is a real miss. We kept the
  grader strict and did not count these as found.
- **The pie chart by product name (RPT103) is the least stable judgment item.** One run in three reported it as its
  own finding; the others mention it in passing or not at all. It is low severity, so we left it.
- **Sample:** run bad2 is published unedited as [`examples/sample-review.md`](../examples/sample-review.md).

### Reproduce

```bash
python tests/eval/run_eval.py --fixture bad  --workdir /tmp/pbi-eval/bad1
python tests/eval/run_eval.py --fixture good --workdir /tmp/pbi-eval/good1
python tests/eval/grade.py /tmp/pbi-eval/bad1 --fixture bad      # re-grade an existing run
```

Results vary between runs (model sampling), so run at least three per fixture.

## 3. PR mode (end to end)

**Setup:** GoodModel on `main`; a branch with three planted changes:

1. `[Margin]` changed from `[Sales Amount] - [Total Cost]` to `/`. It is still described and formatted as currency, and it feeds `[Margin %]` and 3 visuals.
2. `Customer[Segment]` removed. A drill-through table still uses it.
3. A new measure `[Avg Line Value]` uses `/`.

The prompt was "review my changes on this branch against main". The script that builds the scenario is in the session notes; it is reproducible by hand in a minute.

| Run | Margin semantic change | Broken visual (PR001) | `/` in new measure | Pre-existing issues flagged | PR_COMMENT.md | Project modified |
|---|---|---|---|---|---|---|
| pr1 (before checklist) | ✅ (as DAX101) | ✅ | ✅ | none | ❌ skipped, free-form REVIEW.md | no |
| pr2 | ✅ DAX106, names `[Margin %]` + 3 visuals | ✅ | ✅ | none | ✅ | no |
| pr3 | ✅ DAX106, names `[Margin %]` + 3 visuals | ✅ | ✅ | none | ✅ | no |

pr1 found all three issues but skipped the template and custom-rules files on a small diff. We added a 4-step
"every review, both modes" checklist to the top of SKILL.md. pr2 and pr3 ran after that change. A BadModel full review
re-run after the change still scored 41/43 = 95% recall (6/7 judgment), so the checklist cost nothing in recall.
