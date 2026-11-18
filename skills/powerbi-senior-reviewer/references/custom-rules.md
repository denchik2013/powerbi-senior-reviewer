# Custom rules (team / author conventions)

**Always read this file.** These rules come from the people who own the models. When a custom rule conflicts with a
general rule in `rules-*.md`, **the custom rule wins**. Say so in the finding ("per team rule CUS00X").

Custom rules are applied by the reviewer (you), not by the scripts: the scripts stay generic so this file can be edited
freely. Use `out/inventory.json` to check them quickly, then cite `file:line` as for any other finding. When a custom rule
tightens a static rule, report **one** finding with the custom id and record the static one as `dropped` in
`judgment.json` (reason: "superseded by CUS00X").

Format for each rule:

```
### CUSxxx · <short title> · <severity: Critical|High|Medium|Low|Nit> · <area: Model|DAX|Power Query|Report|Security|Governance>
**Rule:** what must (not) be true, stated so it can be checked.
**Why:** the reason, one or two sentences.
**Check:** how to verify it (which file / field / pattern to look at).
**Bad → Good:** a short example.
**Overrides:** rule id(s) it replaces or tightens, or "none".
**Exceptions:** when it does not apply.
```

> **Provenance.** Default set (reviewed 2026-11), drafted from widely used public guidance and written in our own words:
> SQLBI DAX style, naming and UDF articles, Microsoft Learn Power BI guidance (including *Prepare your data for AI* and
> incremental refresh), Tabular Editor's naming-conventions, BPA and UDF-vs-calculation-group articles. Edit, delete or
> add rules to match your team: this file is meant to be owned by you.

---

### CUS001 · All measures live in `_Measures` · Medium · Governance
**Rule:** every visible measure is defined in one measure table named `_Measures` (no visible columns), and every measure
there has a `displayFolder`.
**Why:** one place to find every KPI; measures do not disappear when a fact table is replaced or re-imported.
**Check:** `inventory.json` → measures with `table != "_Measures"` and `isHidden == false`; measures in `_Measures` without
`displayFolder`.
**Bad → Good:** `table Sales / measure 'Total Sales' = …` → move it to `table _Measures` with `displayFolder: Sales`.
**Overrides:** GOV002 (stricter: applies to any model size; "measures on their fact table" is not an accepted exception).
**Exceptions:** calculation-group items; hidden helper measures may stay next to the logic they serve.

### CUS002 · Report users see measures, not raw fact columns · Medium · Model
**Rule:** numeric columns of fact tables (amounts, quantities, prices, costs) are hidden; every number shown in a report
comes from an explicit measure.
**Why:** a visible numeric column invites implicit sums and averages that nobody reviewed and that break on
non-additive values (prices, rates, percentages).
**Check:** `inventory.json` → fact tables (`ModelIndex.fact_tables`) → columns with a numeric `dataType` and
`isHidden == false`. Report fields with `Aggregation` (DAX009) usually point to the same columns.
**Bad → Good:** visible `Sales[Quantity]` dragged in as "Sum of Quantity" → `isHidden` on the column + `measure 'Order
Quantity' = SUM(Sales[Quantity])` in `_Measures`.
**Overrides:** DAX009 (report it once, under CUS002, listing the visuals that use the implicit measure).
**Exceptions:** degenerate attributes on the fact table that users filter by (order number, line status).

### CUS003 · Keys are `<Entity>Key`, whole numbers, hidden · Low · Model
**Rule:** columns used in relationships are named `<Entity>Key` (e.g. `CustomerKey`), have `dataType: int64`,
`isHidden` and `summarizeBy: none`.
**Why:** integer keys compress and join best; a consistent name tells everyone which columns are plumbing, and hidden keys
keep them out of visuals.
**Check:** `relationships.tmdl` → both columns of each relationship → their column block in the table file.
**Bad → Good:** `Sales[customer_code]` (string, visible) → `Sales[CustomerKey]` (int64, hidden) mapped in Power Query or
upstream.
**Overrides:** MOD005, MOD006, MOD007 when they hit a key (report one CUS003 finding per relationship, not three).
**Exceptions:** relationships to a date table on a `date`/`dateTime` column; business codes that users search by may stay
visible as a separate `… Code` column next to the hidden key.

### CUS004 · Business-friendly names for everything visible · Low · Governance
**Rule:** visible tables, columns and measures use words separated by spaces in Title Case (`Customer Name`,
`Sales Amount`). No technical prefixes or suffixes (`dim_`, `fact_`, `tbl`, `vw_`, `_ID`), no snake_case, no camelCase,
acronyms only when the business uses them.
**Why:** names are the user interface of the model: people (and Copilot / Q&A) search the field list by business words.
**Check:** `inventory.json` → objects with `isHidden == false` whose name matches `^(dim|fact|tbl|vw)_?`, contains `_`,
or is camelCase / all lowercase.
**Bad → Good:** `dim_store` → `Store`; `FactBudget` → `Budget`; `avg_price` → `Average Price`.
**Overrides:** GOV003 (report naming once, under CUS004, with the full list).
**Exceptions:** hidden objects; the `_Measures` table name; single-word names (`Email`, `Region`).

### CUS005 · Time-intelligence suffixes · Low · DAX
**Rule:** time-shifted measures use a fixed suffix: ` PY`, ` YTD`, ` QTD`, ` MTD`, ` YoY`, ` YoY %`, ` MoM %`.
**Why:** users recognise the variant at a glance and can find all variants of a KPI by its base name.
**Check:** measures calling SAMEPERIODLASTYEAR / DATEADD / PARALLELPERIOD / DATESYTD / DATESMTD / TOTALYTD (directly or via
another measure) whose name lacks the matching suffix.
**Bad → Good:** `[Last Year Sales]` → `[Sales PY]`; `[Sales Growth %]` → `[Sales YoY %]`.
**Overrides:** none (adds to GOV003).
**Exceptions:** none.

### CUS006 · Every visible measure has a format string and a business description · Low · Governance
**Rule:** each visible measure has `formatString` (or `formatStringDefinition`) and a `///` description that says what
it means in business terms: unit or currency, grain, and any filter it applies. A description that only repeats the
formula (`Sum of Amount`) does not count.
**Why:** descriptions are the tooltip in the field list and the main context Copilot and Fabric data agents read to pick
the right measure; a missing format string shows raw decimals.
**Check:** `inventory.json` → visible measures with empty `formatString`/`formatStringExpression` or empty `description`.
**Bad → Good:** `measure 'Total Cost' = SUM(…)` with nothing else → `/// Cost of goods sold in USD, quantity × unit
cost, all order lines.` + `formatString: \$#,0`.
**Overrides:** DAX004 and DAX005 (stricter: all visible measures, not only those used in the report).
**Exceptions:** hidden helper measures.

### CUS007 · Bi-directional filtering needs a written reason · High · Model
**Rule:** `crossFilteringBehavior: bothDirections` is allowed only when the relationship carries an annotation
`annotation BidiReason = <why>`; otherwise use single direction (and CROSSFILTER in the one measure that needs it).
**Why:** bi-directional filters create ambiguous paths, slow queries and can widen what an RLS role sees; a reason forces
the author to think about it.
**Check:** `relationships.tmdl` → relationships with `bothDirections` and no `BidiReason` annotation.
**Bad → Good:** `crossFilteringBehavior: bothDirections` alone → remove it, or keep it with
`annotation BidiReason = Customer slicer must list only customers with sales in the selected period`.
**Overrides:** MOD001 (with a documented reason, downgrade MOD001 to a Low note; without one it stays High).
**Exceptions:** none.

### CUS008 · No calculated columns on fact tables · Medium · Model
**Rule:** fact tables contain no DAX calculated columns; derive columns in Power Query or upstream in the source.
**Why:** "as far upstream as possible, as far downstream as necessary": calculated columns on large tables are not
compressed as well, are recalculated on every refresh and cannot be folded to the source.
**Check:** `inventory.json` → columns with `isCalculated == true` on fact tables.
**Bad → Good:** `column 'Line Total' = Sales[Quantity] * Sales[Unit Price]` → a measure
`SUMX(Sales, Sales[Quantity] * Sales[Unit Price])`, or an added column in the Power Query step.
**Overrides:** MOD009 (stricter: any calculated column on a fact table, not only row-level arithmetic).
**Exceptions:** columns that need model context (e.g. a `RELATED` lookup used for a sort) on small tables, documented in
the column's `///` description.

### CUS009 · RLS through a mapping table and USERPRINCIPALNAME() · High · Security
**Rule:** role filters never contain e-mail addresses or names; they filter a hidden security mapping table
(user → allowed key) with `USERPRINCIPALNAME()`, and the mapping table filters the dimension through a relationship.
**Why:** hard-coded identities need a model change for every joiner and leaver; `USERNAME()` returns different formats
in Desktop and the service, so roles that pass testing fail in production.
**Check:** `roles/*.tmdl` → `tablePermission` expressions containing `@`, quoted names, or `USERNAME()`.
**Bad → Good:** `tablePermission dim_store = [Region] = "North" && USERNAME() = "anna@…"` →
`tablePermission Security = [UserPrincipalName] = USERPRINCIPALNAME()` with `Security[Region]` → `Store[Region]`.
**Overrides:** SEC002 (merged into CUS009), SEC003 (raised from Low to High).
**Exceptions:** static roles with no user identity at all (e.g. a "Europe only" role assigned to a group in the service).

### CUS010 · Executive pages: at most 8 data visuals · Medium · Report
**Rule:** pages whose name contains `Exec`, `Overview`, `Summary` or `Dashboard` have at most 8 data visuals
(shapes, text boxes, images and buttons excluded).
**Why:** leadership reads these in a meeting on a laptop; more than 8 visuals means the page has no single message.
**Check:** `inventory.json` → page visuals excluding decorative types; compare with RPT001 output.
**Bad → Good:** 17 visuals on "Overview" → 4 KPI cards + 2 trend charts + 2 breakdowns; detail moves to a drill-through
page.
**Overrides:** RPT001 (threshold 8 instead of 15 for these pages).
**Exceptions:** pages whose name ends with `Detail`.

### CUS011 · Time-intelligence variants come from one place · Medium · DAX
**Rule:** when three or more base measures each get the same time variants (PY, YTD, YoY %…), the logic lives in one
place: a calculation group, or DAX user-defined functions (UDFs) called by thin measures. No copy-pasted
`CALCULATE(…, SAMEPERIODLASTYEAR(…))` per base measure.
**Why:** copy-pasted variants drift (one uses `DATEADD`, another `SAMEPERIODLASTYEAR`, a third forgets the date filter) and
every new KPI adds five more measures to maintain. Calculation groups suit uniform patterns over many measures; UDFs suit
more complex, parameterised logic that still needs to be a named measure.
**Check:** measures calling time-intelligence functions; group them by base measure; ≥ 3 bases with the same wrapper and
no `calculationGroup` table / `function` definitions in the model → finding.
**Bad → Good:** `[Sales PY]`, `[Cost PY]`, `[Margin PY]`, `[Orders PY]` each with its own SAMEPERIODLASTYEAR →
a `Time Intelligence` calculation group with a `PY` item, or a UDF `PY(m)` and `measure 'Sales PY' = PY([Sales Amount])`.
**Overrides:** none (adds to DAX105).
**Exceptions:** models where fewer than three base measures need time variants.

### CUS012 · Incremental refresh filters fold to the source · High · Power Query
**Rule:** a table with an incremental refresh policy (`refreshPolicy`, or M that uses `RangeStart` / `RangeEnd`) filters
on `RangeStart`/`RangeEnd` directly after the navigation step, on a column of the source's date type, using `>=` on one
bound and `<` on the other, before any added column, merge or type change.
**Why:** if the filter does not fold, every partition refresh reads the whole source table and filters in the mashup
engine: refreshes get slower instead of faster, and with `<=` on both bounds rows on the boundary load twice.
**Check:** partition `source` / `refreshPolicy` M in the table's TMDL: the step order and the comparison operators.
**Bad → Good:** `AddedYear = Table.AddColumn(…), Filtered = Table.SelectRows(AddedYear, each [OrderDate] >= RangeStart
and [OrderDate] <= RangeEnd)` → `Filtered = Table.SelectRows(Navigation, each [OrderDate] >= RangeStart and [OrderDate] <
RangeEnd)` as the first step after navigation.
**Overrides:** PQ101 (raised to High for incremental-refresh tables).
**Exceptions:** sources that cannot fold (files): incremental refresh there should be questioned, not tuned.

### CUS013 · Source control uses the current text formats · Low · Governance
**Rule:** projects in git store the model as TMDL (`definition/*.tmdl`, no `model.bim`) and the report as PBIR
(`definition/` folder, no single `report.json`).
**Why:** both are line-based and diff cleanly, so pull requests can be reviewed line by line (and by this skill). TMSL and
the legacy report JSON produce huge one-line diffs and merge conflicts.
**Check:** inventory warnings mentioning TMSL / `model.bim` or the legacy report format.
**Bad → Good:** `Model.SemanticModel/model.bim` → Power BI Desktop → Options → Preview features → *Store semantic model
using TMDL format*, then save; legacy report → save once with PBIR enabled.
**Overrides:** none.
**Exceptions:** none.

### CUS014 · Colours come from the theme · Low · Report
**Rule:** visuals do not hard-code colours (hex literals such as `'#1F77B4'` in `visual.json` objects); colours,
fonts and default styles come from the report theme. Data-driven conditional formatting is fine.
**Why:** hard-coded colours drift from page to page, break when the brand changes, and often fail contrast in dark or
high-contrast modes; a theme changes them all at once.
**Check:** `visual.json` files containing a `"Literal"` whose value is a hex colour, outside conditional-formatting rules.
**Bad → Good:** a column chart with `"fill": {"solid": {"color": {"expr": {"Literal": {"Value": "'#118DFF'"}}}}}` →
remove the override and set `dataColors` in the theme JSON.
**Overrides:** none (sharpens RPT102).
**Exceptions:** one-off highlight colours that carry meaning (e.g. a red target line) and are used consistently.

