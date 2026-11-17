# Governance and PR hygiene rules

`[S]` = reported by `static_checks.py` / `diff_scope.py`; `[J]` = your judgment.

## Contents
GOV001 local cache not git-ignored · GOV002 measure organisation · GOV003 naming · PR001 broken references · PR002 PR size / mixed concerns

---

### GOV001 · `.pbi/cache.abf` / `localSettings.json` not git-ignored · 🟡 Medium (🔴 Critical if `cache.abf` is committed) `[S]`
**Why:** `cache.abf` is the local copy of imported **data**: committing it publishes the data. `localSettings.json` is per-user noise that causes merge conflicts.
**Fix:**
```gitignore
**/.pbi/localSettings.json
**/.pbi/cache.abf
```
If already committed: `git rm --cached <path>`. If `cache.abf` contained real data, history must be rewritten (`git filter-repo`) and the exposure treated as a data incident.
The check uses `git check-ignore`, so patterns in any `.gitignore` (repo root or project folder) count.

### GOV002 · Measures not organised · 🔵 Low `[S]`
Fires when there are 6+ visible measures, no dedicated measure table, and most measures have no display folder.
**Fix:** a measure table (`_Measures`, all columns hidden) plus `displayFolder:` by business area (Sales, Profitability, Time Intelligence).
**Not a problem when:** a small model where measures sit on their natural fact table *and* use display folders: that is a valid convention too.

### GOV003 · Inconsistent naming conventions · 🔵 Low `[S]`
The script groups visible table/column/measure names into styles (Spaced Words, snake_case, PascalCase, camelCase, dim/fact prefixes) and fires if more than one is in use.
**Fix:** one convention for **visible** objects, usually business-friendly `Title Case With Spaces`, no `dim_`/`Fact` prefixes. Hide technical columns instead of renaming them. Rename in Power Query or the source view, not with `DAX` aliases.
**Not a problem when:** codes and acronyms (`SKU`, `KPI Status`) or names imposed by an external standard. Mention them and move on.

### PR001 · Broken references after the change · 🔴 Critical `[S]` (`diff_scope.py` → `brokenReferences`)
A measure, calculated column, RLS rule or visual still references a removed/renamed column or measure. The report shows an error ("Something's wrong with one or more fields") or the model fails to load.
**Fix:** update the references in the same PR, or keep the old name.

### PR002 · PR size and mixed concerns · 🔵 Low `[J]`
A PR that renames 40 columns, rewrites measures and redesigns pages at once cannot be reviewed meaningfully. Suggest splitting (model refactor / measure logic / report layout) when `changedFiles` is large and spans model and report for unrelated reasons.
