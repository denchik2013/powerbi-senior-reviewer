# Power BI Senior Reviewer

**A Claude skill that reviews Power BI projects the way a senior developer would: on your PR, offline, with `file:line`
evidence and fixes you can paste.**

A linter can see that `[Total Revenue]` has no description. A senior reviewer sees that `[Total Revenue] = COUNTROWS(Sales)`
is formatted as dollars, so the Overview card shows 12 431 orders as **$12,431**. This skill does both: deterministic
checks in plain Python, then Claude's judgment on what the numbers actually mean.

- **Full review** of a PBIP project: semantic model (TMDL) + report (PBIR).
- **PR review**: only what changed in `git diff`; new problems only, plus broken references and the visuals whose numbers
  change.
- **Health score 0–100** with per-area scores (Model, DAX, Power Query, Report, Security, Governance), a top-3 "fix first",
  findings by severity 🔴 🟠 🟡 🔵 ⚪, each with *where* (`file:line` + quoted code), *why*, and a ready-to-paste DAX / TMDL / M fix.
- **Your team's rules win**: write conventions in plain English in [`custom-rules.md`](skills/powerbi-senior-reviewer/references/custom-rules.md).
- **Nothing leaves your machine.** Python standard library only, no network code (checked in CI), no telemetry.

## What a review looks like

Unedited excerpt from [`examples/sample-review.md`](examples/sample-review.md), a real run on the `BadModel` test fixture:

```markdown
# Power BI review: BadModel

**Health score: 46/100** · Full review · 2026-11-18

| Model | DAX | Power Query | Report | Security | Governance |
|:-:|:-:|:-:|:-:|:-:|:-:|
| 5 | 26 | 56 | 84 | 66 | 97 |

The numbers on this report can't be trusted yet. "Revenue" counts rows, average order value is weighted by line
count, and budget can't be sliced by anything but category. A database password is committed in M code, and
row-level security is one hard-coded e-mail address.

## Fix these first
1. **Rotate and remove the ODBC password** · `…/tables/Product.tmdl:39` · it is readable by anyone with the repo and stays in git history.
2. **`[Total Revenue]` is `COUNTROWS`** · `…/tables/Sales.tmdl:15` · a row count is shown as `$12,431`.
3. **RLS is one hard-coded e-mail and leaves FactBudget and Customer contact data exposed** · `…/roles/Regional Managers.tmdl:4`.
```

…and every finding gets a block like this:

````markdown
#### DAX102 · `Avg Order Value` is averaged per line, not per order
**Where:** `tables/Sales.tmdl:31`
```dax
AVERAGEX(
    Sales,
    SUMX(
```
**Why it matters:** `AVERAGEX(Sales, …)` visits each order line, so a 10-line order counts ten times. The result
also leans on `EARLIER`.
**Fix:**
```dax
measure 'Avg Order Value' = DIVIDE([Total Sales], DISTINCTCOUNT(Sales[OrderID]))
```
````

No linter flags that measure as wrong. Catching it takes knowing what "average order value" means.

## Install

**Claude Code (plugin marketplace)**, one command each:

```
/plugin marketplace add denyssokotov/powerbi-senior-reviewer
/plugin install powerbi-senior-reviewer@powerbi-senior-reviewer
```

**Claude Code (manual)**: copy the skill folder into your personal skills:

```bash
git clone https://github.com/denyssokotov/powerbi-senior-reviewer
cp -r powerbi-senior-reviewer/skills/powerbi-senior-reviewer ~/.claude/skills/
```

(or into `<your repo>/.claude/skills/` to share it with your team through git).

**Claude.ai / Claude desktop app**: zip the skill folder and upload it under *Settings → Capabilities → Skills*:

```bash
cd powerbi-senior-reviewer/skills && zip -r powerbi-senior-reviewer.zip powerbi-senior-reviewer
```

The frontmatter uses only portable keys, so the same folder works in Claude Code, Claude.ai and the Skills API. Code
execution must be enabled for the scripts to run.

**Requirements:** Python 3.10+ (no packages), `git` for PR mode. Windows, macOS, Linux. Your project must be saved as
**PBIP with TMDL** (Power BI Desktop → Options → Preview features → *Power BI Project (.pbip) save option* and *Store
semantic model using TMDL format*). PBIR report format is fully supported; the legacy `report.json` gets a partial review.

## Use

Open Claude Code in the repository that contains your `.pbip` and ask:

| You say | What happens |
|---|---|
| `review my Power BI project` | Full review → `out/REVIEW.md` + summary in chat |
| `review this PR` / `review my changes against main` | PR review of `git diff` → `out/REVIEW.md` + `out/PR_COMMENT.md` |
| `is my DAX ok?` · `check this PBIP` · `audit my semantic model` | Full review, focus follows the question |
| `fix #1` / `fix the critical ones` | Applies fixes one at a time, shows each edit, re-runs the checks |

The skill never edits your project unless you ask, and never posts to GitHub unless you ask (it shows the comment
first). Add `out/` to your `.gitignore`.

Under the hood:

```
pbip_inventory.py  → out/inventory.json   every table, column, measure, relationship, role, page, visual with file:line
field_usage.py     → out/usage.json       what is used where (DAX, relationships, visuals, filters); unused objects
diff_scope.py      → out/scope.json       PR mode: added / modified / removed objects, dependents, broken references
static_checks.py   → out/findings.json    38 deterministic rules + health score
Claude             → out/REVIEW.md        verifies every static finding, adds judgment findings, writes the review
```

You can run the scripts yourself (e.g. in CI) without Claude:

```bash
S=skills/powerbi-senior-reviewer/scripts
python $S/pbip_inventory.py path/to/project -o out/inventory.json
python $S/static_checks.py --inventory out/inventory.json -o out/findings.json --list-rules
```

## Your own rules

Edit [`skills/powerbi-senior-reviewer/references/custom-rules.md`](skills/powerbi-senior-reviewer/references/custom-rules.md).
Each rule is a short block in plain English:

```markdown
### CUS011 · Measures that end with % use DIVIDE · Medium · DAX
**Rule:** …   **Why:** …   **Check:** …   **Bad → Good:** …   **Overrides:** DAX002   **Exceptions:** …
```

Custom rules override the built-in ones when they conflict, and the review says "per team rule CUS011". The file ships
with ten defaults (measure table, hidden keys, business-friendly names, time-intelligence suffixes, RLS via a mapping
table, at most 8 visuals on executive pages…) drafted from public guidance: keep, change or delete them.

Turn off a built-in rule for a run: `static_checks.py --disable MOD006,GOV003`.

## Privacy

- The scripts are Python standard library only, read files from disk and write JSON to `out/`. CI fails the build if any
  script imports a network module (`socket`, `http`, `urllib`, …) or contains a URL.
- Claude reads your TMDL / PBIR files to write the review, the same as any code review in Claude Code. Your data is
  never read: PBIP stores metadata and M/DAX code, not rows (`.pbi/cache.abf` is ignored).
- Secrets found in M code are masked (`pwd=***`) in every output.
- **Reviewing a client's model?** Run it through [**PBI Twin**](https://github.com/denyssokotov/pbi-twin) first: it creates an
  anonymized twin of the model (same measures, relationships and report, fake data, 100% local), so you can review it
  or share it without exposing real data or names.

## How good is it?

Measured on two fixtures in [`tests/fixtures`](tests/fixtures): `BadModel` with 43 planted problems
([list](tests/expected-issues.md)) and a clean `GoodModel`. Full method and per-run numbers in
[`docs/EVALS.md`](docs/EVALS.md).

| | Static scripts alone | Full skill (3 runs, final version) | Target |
|---|---|---|---|
| Recall on BadModel, all 43 issues | 84% | **98% · 98% · 91%** | ≥ 85% |
| Recall, the 7 judgment-only issues (wrong logic, grain, RLS reach…) | 0% | **86% · 86% · 86%** | – |
| False findings on GoodModel | 0 | **0 · 0 · 0** | ≤ 3 |
| Findings citing a real `file:line` | 100% | **100%** | 100% |
| Project files modified during review | – | **none** | none |

The judgment row is what separates this skill from a linter: "Total Revenue counts rows", "average order value is
weighted by lines", "budget at category grain is sliced by product", and "the role never reaches the budget table" are
not pattern-matchable.

## Rules

38 deterministic rules + 17 judgment rules (plus 10 editable team rules), documented with *why it matters*, *bad → good* and *when it is not a problem*:
[model](skills/powerbi-senior-reviewer/references/rules-model.md) ·
[DAX](skills/powerbi-senior-reviewer/references/rules-dax.md) ·
[Power Query](skills/powerbi-senior-reviewer/references/rules-power-query.md) ·
[report](skills/powerbi-senior-reviewer/references/rules-report.md) ·
[security](skills/powerbi-senior-reviewer/references/rules-security.md) ·
[governance & PR](skills/powerbi-senior-reviewer/references/rules-governance.md).

## Limitations

- TMDL only for the model (a TMSL `model.bim` gets a warning and a manual review); the legacy `report.json` report
  format is parsed partially.
- Judgment findings vary a little between runs, like any reviewer; low-severity design remarks are the least stable.
- `out/inventory.json` keeps raw M code (secrets are masked in findings and reviews, not in this local working file):
  keep `out/` git-ignored.
- No data volumes are read, so performance findings rank by pattern, not by measured cost.

## Roadmap

- TMSL (`model.bim`) parsing and fuller legacy `report.json` support.
- Optional VertiPaq statistics input (column sizes from DAX Studio export) to rank performance findings by real cost.
- GitHub Action that posts `PR_COMMENT.md` on pull requests touching `*.SemanticModel` / `*.Report`.
- Calculation groups and field parameters: deeper DAX checks.
- More fixtures (DirectQuery, composite models, Direct Lake) and a larger eval set.

## Credits and related work

The rules are written in our own words, informed by public guidance from:
[Tabular Editor Best Practice Rules](https://github.com/TabularEditor/BestPracticeRules) (MIT),
[SQLBI](https://www.sqlbi.com/) (DAX style, naming and modeling articles),
[Microsoft Learn Power BI guidance](https://learn.microsoft.com/power-bi/guidance/),
the [Tabular Editor naming-conventions article](https://tabulareditor.com/blog/naming-conventions-for-power-bi-semantic-models), and
[Data Goblins `power-bi-agentic-development`](https://github.com/data-goblin/power-bi-agentic-development) (GPL-3.0; no
code or text copied). Complementary tools for *building* Power BI artifacts with agents:
[Microsoft skills-for-fabric](https://github.com/microsoft/skills-for-fabric) and Data Goblins. See
[`docs/LANDSCAPE.md`](docs/LANDSCAPE.md) for how they compare.

## Development

```bash
python -m unittest discover -s tests -v              # unit tests (stdlib only)
python .github/scripts/check_no_network.py skills     # the CI no-network check
python tests/eval/run_eval.py --fixture bad --workdir /tmp/eval-1   # end-to-end eval (calls Claude, costs tokens)
claude plugin validate .
```

## License

MIT, see [LICENSE](LICENSE).
