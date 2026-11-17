# Model rules

`[S]` = reported by `static_checks.py` (verify, then keep, adjust or drop). `[J]` = your judgment: look for it yourself.
Every entry ends with **Not a problem when**: read it before keeping a finding.

## Contents
MOD001 bi-directional · MOD002 many-to-many · MOD003 auto date/time · MOD004 no date table · MOD005 text keys ·
MOD006 visible keys · MOD007 default summarization · MOD008 high cardinality · MOD009 calc column → PQ ·
MOD010 unused columns · MOD011 Double money · MOD012 dead inactive relationship ·
MOD101 not a star · MOD102 ambiguous paths · MOD103 grain mismatch

---

### MOD001 · Bi-directional cross-filtering · 🟠 High `[S]`
**Why:** Filters flow both ways, so a slicer on one fact can filter another fact through a shared dimension. You get several filter paths (the engine picks one, silently), slower queries, and RLS filters that reach tables they were not meant to.
**Bad:** `crossFilteringBehavior: bothDirections` on `Sales[CustomerKey] -> Customer[CustomerKey]`.
**Good:** single direction; enable the reverse only inside the measure that needs it:
```dax
Customers With Sales = CALCULATE ( DISTINCTCOUNT ( Customer[CustomerKey] ), CROSSFILTER ( Sales[CustomerKey], Customer[CustomerKey], BOTH ) )
```
**Not a problem when:** the relationship is the dimension→bridge side of a deliberate many-to-many bridge pattern (severity drops to Medium automatically), or a one-to-one split of the same entity (Low). Still ask whether a measure-level CROSSFILTER would do.

### MOD002 · Many-to-many relationship · 🟡 Medium `[S]`
**Why:** M:M relationships hide a grain mismatch. Totals do not add up to the visible rows and authors cannot tell why.
**Bad:** `FactBudget[Category]` *:* `Product[Category]`.
**Good:** a `Category` dimension with one row per category, related one-to-many to both `Product` and `FactBudget`.
**Not a problem when:** it is a documented, intentional pattern (e.g. a security or tag bridge), the team understands the non-additive totals, and the relationship is single-direction.

### MOD003 · Auto date/time enabled · 🟠 High `[S]`
**Why:** Power BI creates a hidden `LocalDateTable_*` for every date column. That adds memory, and each date column gets its own calendar, so time intelligence is inconsistent and nothing can be marked as *the* date table.
**Bad:** `annotation __PBI_TimeIntelligenceEnabled = 1` in `model.tmdl`, `LocalDateTable_…` tables present.
**Good:** turn it off (Options → Current file → Data load). The annotation becomes `0`, and the model has one marked Date table.
**Not a problem when:** a throwaway prototype. Never in a shared/production model.

### MOD004 · No marked date table · 🟡 Medium / 🟠 High with time intelligence `[S]`
**Why:** time-intelligence functions assume a contiguous calendar marked as date table. Without one, `SAMEPERIODLASTYEAR`, `DATESYTD`, etc. return wrong or blank results once filters are not on the date column itself.
**Good:** a calendar table with `dataCategory: Time` and its date column `isKey`, related to each fact's date key.
**Not a problem when:** the model has no date logic at all (no relationships on dates, no time intelligence): then it stays Medium or can be dropped.

### MOD005 · Relationship on text keys · 🟡 Medium `[S]`
**Why:** string keys compress worse and join slower than integers, and invisible differences (case, trailing spaces) break joins silently.
**Good:** integer surrogate keys from the warehouse or created in Power Query; keep the code as a visible attribute.
**Not a problem when:** small dimensions (<~10k rows) where the source only has a natural text code and adding a surrogate is impossible. Lower to Low and say so.

### MOD006 · Visible relationship keys · 🟡 Medium (fact side) / 🔵 Low (dimension side) `[S]`
**Why:** users drag `Sales[ProductKey]` instead of `Product[Product Name]`. Fact-side keys filter only that fact, not the dimension, so visuals disagree.
**Good:** `isHidden` on key columns. Expose attributes, not keys.
**Not a problem when:** a dimension's natural code is a business identifier people search by (e.g. `Order Number`, `Customer Code` on the dimension). Keep it visible, but on the dimension, not the fact.

### MOD007 · Numeric key / calendar column summarizes · 🔵 Low `[S]`
**Why:** `Year`, `MonthNumber`, `ProductKey` show up as "Sum of Year = 4 046 238". It looks broken and invites implicit measures.
**Good:** `summarizeBy: none`.
**Not a problem when:** the column really is additive (rare for anything named Key/ID/Year).

### MOD008 · High-cardinality column · 🟡 Medium (🟠 High if in a relationship) `[S]`
**Why:** a datetime with seconds or a GUID is near-unique, which defeats dictionary compression. One such column can be most of the model size.
**Good:** split `OrderDateTime` into `OrderDate` (date) and, if needed, `OrderTime` rounded to the minute/hour. Drop GUIDs no report needs.
**Not a problem when:** DirectQuery tables (no import storage), or the time part is genuinely required at that grain and the table is small.

### MOD009 · Row-level calculated column → Power Query · 🟡 Medium `[S]`
**Why:** a calculated column that only uses its own row (`Sales[Qty] * Sales[Price]`) is computed after load, is not compressed as well as a source column, and is evaluated on every refresh.
**Good:** `Table.AddColumn(prev, "Line Total", each [Quantity] * [Unit Price], Currency.Type)` or compute in the source view. Often you need no column at all: `SUMX(Sales, Sales[Quantity] * Sales[Unit Price])`.
**Not a problem when:** the source is not foldable and Power Query would be slower, the table is tiny, or the column feeds a relationship or sort that must stay in DAX.

### MOD010 · Unused columns · 🔵 Low `[S]` (from `field_usage.py`)
**Why:** every imported column costs memory and refresh time, and clutters the field list.
**Good:** remove early in Power Query with `Table.SelectColumns`.
**Not a problem when:** other reports on the same model live in another repository (live-connected thin reports): say "unused in this repository" and ask. `reportCoverage: none` means no report was found and the rule is skipped.

### MOD011 · Money stored as Double · 🔵 Low `[S]`
**Why:** binary floating point cannot represent most decimal fractions, so sums drift (0.1 + 0.2 ≠ 0.3) and Double compresses worse than Fixed Decimal (4 decimal places).
**Good:** `Currency.Type` in Power Query → `dataType: decimal`.
**Not a problem when:** you need more than 4 decimal places (exchange rates, scientific values).

### MOD012 · Inactive relationship never used · 🟡 Medium `[S]`
**Why:** an inactive relationship does nothing until a measure calls `USERELATIONSHIP`. Unused, it misleads readers of the model diagram.
**Good:**
```dax
Sales by Ship Date = CALCULATE ( [Total Sales], USERELATIONSHIP ( Sales[ShipDate], 'Date'[Date] ) )
```
**Not a problem when:** it is used by a calculation group item or by thin reports' report-level measures outside this repo (check and say so).

### MOD101 · Not a star schema · 🟡 Medium `[J]`
Look for: dimension → dimension chains (snowflake) with no reason, fact-to-fact relationships, "header/detail" facts related to each other, wide flat tables mixing facts and attributes.
**Why:** every extra hop costs performance and makes filter behavior harder to reason about. Fact-to-fact joins almost always mean a missing shared dimension.
**Fix:** flatten small snowflakes into the dimension in Power Query; relate facts only through shared (conformed) dimensions.
**Not a problem when:** a large, shared dimension is deliberately normalized for size (e.g. Product → Subcategory with millions of products).

### MOD102 · Ambiguous filter paths · 🟠 High `[J]`
Look for: two active routes between the same tables (usually caused by bi-directional relationships or a role-playing dimension related twice).
**Why:** Power BI deactivates or chooses a path for you, so numbers depend on a choice nobody made explicitly.
**Fix:** one active path; role-playing dimensions get inactive relationships + `USERELATIONSHIP` measures, or separate copies (Order Date / Ship Date).

### MOD103 · Grain mismatch between related tables · 🟠 High `[J]`
Look for: a fact at a coarser grain (budget per category per month) related to a finer dimension (product), or a fact without a date relationship that will be sliced by date.
**Why:** sliced by the finer attribute, every product shows the full category budget (repeated, not split); "Budget vs Actual" by product is fiction.
**Fix:** relate at the shared grain (a `Category` dimension; `Date` at month level via a month key), and hide or guard measures with `ISINSCOPE` at grains they do not support:
```dax
Budget Amount =
IF ( NOT ISINSCOPE ( Product[Product Name] ), SUM ( FactBudget[Amount] ) )
```
