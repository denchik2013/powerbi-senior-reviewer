# Power Query (M) rules

`[S]` = reported by `static_checks.py`; `[J]` = your judgment. M code lives in each table's `partition … = m` → `source =` block and in `expressions.tmdl`.

## Contents
PQ001 hard-coded source · PQ002 secrets · PQ003 Table.Buffer · PQ004 repeated change type · PQ101 folding breakers · PQ102 late column removal

---

### PQ001 · Hard-coded path or server · 🟡 Medium `[S]`
**Why:** `File.Contents("C:\Users\jdoe\...")` works on one laptop only; `Sql.Database("PROD-SQL01", ...)` makes dev/test/prod promotion a manual M edit. Deployment pipelines can only swap parameters.
**Bad:** `Source = Sql.Database("PROD-SQL01.contoso.local", "CRM")`
**Good:** in `expressions.tmdl`:
```m
expression ServerName = "sql-dev.example.internal" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]
```
then `Source = Sql.Database(ServerName, DatabaseName)`.
For files: put them on SharePoint/OneDrive for Business or a gateway-reachable share, referenced through a parameter.
**Not a problem when:** the literal is inside a parameter expression itself (that is the right place). The script skips those.

### PQ002 · Credentials or secrets in M · 🔴 Critical `[S]`
**Why:** passwords, API keys, SAS tokens or bearer tokens in M are readable by anyone with the PBIP, PBIX or repo, and stay in git history after you delete them.
**Fix:** remove from M; use data-source credentials in Power BI / the gateway (or a service principal). **Rotate the secret**: assume it is compromised. If committed, history rewrite is needed to purge it.
Never repeat the secret in the review: the script masks it as `***`; keep it masked.

### PQ003 · Table.Buffer · 🔵 Low `[S]`
**Why:** buffering loads the full table into memory and ends query folding for every step after it.
**Keep it when:** a later step reads the same table many times (inside `List.Generate`, `List.Accumulate`, repeated lookups/merges) and the table is small. Otherwise remove it or move it after filters.

### PQ004 · Repeated change-type steps · 🔵 Low `[S]`
**Why:** each auto-generated `Changed Type` step re-types columns; several of them signal steps added by clicking, and the final type is hard to see.
**Good:** one `Table.TransformColumnTypes` with all final types, right after the source/promote-headers step.

### PQ101 · Steps that break query folding · 🟠 High on large SQL sources / 🔵 Low on files `[J]`
Look at foldable sources (SQL, Snowflake, Databricks, OData…). After a non-folding step, every following step runs locally on all rows.
Common breakers: `Table.Buffer`, `Table.AddIndexColumn`, custom functions per row, `Table.Distinct` on many columns, merges with non-foldable queries, type conversions to `type any`, `Table.FirstN` after non-foldable steps, early `Table.TransformColumns` with M-only functions.
**Fix:** filter (`Table.SelectRows`) and select columns first, then do non-foldable steps; push heavy logic into a SQL view.
**Evidence:** quote the step line and the source line it should fold to.

### PQ102 · Columns removed late · 🟡 Medium `[J]`
Look for `Table.RemoveColumns` / `SelectColumns` near the end of a query after merges, expansions or index columns.
**Why:** every intermediate step carries the extra columns; on non-folding sources that is all rows × all columns.
**Fix:** select only needed columns right after navigation (`Source{[Schema="dbo",Item="X"]}[Data]`). Prefer `Table.SelectColumns` (explicit allow-list) over `RemoveColumns`, so new source columns do not leak in.
