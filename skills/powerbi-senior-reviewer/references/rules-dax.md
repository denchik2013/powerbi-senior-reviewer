# DAX rules

`[S]` = reported by `static_checks.py`; `[J]` = your judgment. Check **Not a problem when** before keeping a finding.

## Contents
DAX001 FILTER(table) · DAX002 `/` · DAX003 IFERROR · DAX004 format string · DAX005 description · DAX006 nested iterators ·
DAX007 hard-coded literals · DAX008 ALL vs REMOVEFILTERS · DAX009 implicit measures · DAX010 unused measures ·
DAX101 name ≠ logic · DAX102 double counting / wrong grain · DAX103 time intelligence without date table ·
DAX104 complex without VAR · DAX105 one KPI, several formulas · DAX106 semantic change in PR

---

### DAX001 · FILTER over a whole table inside CALCULATE · 🟠 High `[S]`
**Why:** `FILTER(Sales, ...)` iterates every row of the *expanded* table (including all related dimension columns). It is slow, and it replaces the filter context on all those columns, which changes results in ways the author rarely intends.
**Bad:** `CALCULATE ( [Total Sales], FILTER ( Sales, Sales[Quantity] > 10 ) )`
**Good:** `CALCULATE ( [Total Sales], KEEPFILTERS ( Sales[Quantity] > 10 ) )`
When the condition needs a measure, filter the smallest column set: `FILTER ( VALUES ( Customer[CustomerKey] ), [Total Sales] > 1000 )`.
**Not a problem when:** the table is a small dimension and the condition spans several of its columns with OR logic, *and* the author wants the whole-row semantics. Downgrade to Low and say why.

### DAX002 · `/` instead of DIVIDE · 🟡 Medium `[S]`
**Why:** a zero denominator raises an error or returns ∞; a blank one returns blank or ∞ depending on the numerator. DIVIDE returns BLANK (or your alternate) and is optimized for this.
**Bad:** `([Total Sales] - [Total Cost]) / [Total Sales]`
**Good:** `DIVIDE ( [Total Sales] - [Total Cost], [Total Sales] )`
**Not a problem when:** the denominator is a non-zero constant (`/ 100`): the script already skips numeric literals. Also fine inside iterators where the denominator is provably non-zero *and* performance matters: say so in the evidence.

### DAX003 · IFERROR / ISERROR · 🟡 Medium `[S]`
**Why:** error trapping forces cell-by-cell evaluation in the formula engine and hides data problems you want to see.
**Good:** prevent the error: DIVIDE, `COALESCE`, `IF ( ISBLANK ( … ) )`, or clean data upstream.
**Not a problem when:** converting user-entered text with `VALUE` where no safe alternative exists; keep but note.

### DAX004 · Measures without format string · 🔵 Low `[S]`
**Why:** each visual shows raw numbers (0.153846, 12345678.9); authors format per visual, inconsistently.
**Good:** `formatString: #,0` / `0.0%` / `\$#,0.00`, or a dynamic `formatStringDefinition`.
**Not a problem when:** the measure returns text (labels, titles, colors for conditional formatting). Drop those from the list.

### DAX005 · Report measures without description · 🔵 Low `[S]`
**Why:** the field-list tooltip is empty; Copilot, Q&A and new team members have no definition to rely on.
**Good:** `/// Net sales after discounts, excluding returns.` above the measure.
**Not a problem when:** helper measures that are hidden (the script ignores hidden ones).

### DAX006 · Nested iterators over a fact table · 🟡 Medium `[S]`
**Why:** the inner iterator runs once per outer row, so cost grows with rows², and `EARLIER`-style correlation usually means the grain is being rebuilt in DAX.
**Bad:**
```dax
AVERAGEX ( Sales, SUMX ( FILTER ( Sales, Sales[OrderID] = EARLIER ( Sales[OrderID] ) ), Sales[Quantity] * Sales[Unit Price] ) )
```
**Good:**
```dax
Avg Order Value = AVERAGEX ( VALUES ( Sales[OrderID] ), [Total Sales] )
```
**Not a problem when:** the outer iterator is over a small dimension and the inner one is a measure reference (context transition), e.g. `SUMX ( VALUES ( Customer[Segment] ), [Sales] )`. The script only flags when a fact table is iterated.

### DAX007 · Hard-coded literals · 🟡 Medium `[S]`
**Why:** `'Date'[Year] = 2023` or `Customer[Name] = "Contoso Ltd"` silently go stale and duplicate what slicers/filters should do.
**Good:** relative logic (`'Date'[Year] = MAX ( 'Date'[Year] ) - 1`), a parameter or mapping table (`Customer[Is Key Account] = TRUE`), or leave filtering to the report.
**Not a problem when:** the literal is a stable business constant with a clear name (`'Order'[Status] = "Cancelled"` inside `[Cancelled Orders]`). Lower to Nit or drop.

### DAX008 · ALL as a CALCULATE modifier · ⚪ Nit `[S]`
**Why:** style. `REMOVEFILTERS` says what it does; `ALL` doubles as a table function, which confuses readers.
**Good:** `CALCULATE ( [Total Sales], REMOVEFILTERS ( Sales ) )`. Also consider whether removing filters from the whole fact is right (usually you mean `REMOVEFILTERS ( Product )` or `ALLSELECTED`).

### DAX009 · Implicit measures · 🟡 Medium `[S]`
**Why:** a visual summing a raw column bypasses measure logic, formatting and descriptions, and stops working once calculation groups exist.
**Good:** explicit measures + `discourageImplicitMeasures` in `model.tmdl`.

### DAX010 · Unused measures · ⚪ Nit `[S]`
**Why:** dead measures confuse users and get maintained for nothing.
**Not a problem when:** used by thin reports elsewhere, or work in progress in a hidden "Dev" folder.

### DAX101 · Measure name does not match its logic · 🟠 High (🔴 Critical for finance KPIs) `[J]`
**Check every visible measure on the main pages.** Read the expression and ask: does it compute what the name promises, in the unit the format string implies?
**Examples:** `[Total Revenue] = COUNTROWS ( Sales )` with format `$#,0` counts rows and shows them as dollars. `[Margin %]` divides by cost instead of sales. `[Active Customers]` counts all customers. `[YTD Sales]` without any YTD logic.
**Fix:** correct the formula or rename the measure (and its format). Quote both name and expression in the finding.

### DAX102 · Double counting / wrong granularity · 🟠 High `[J]`
Look for: SUM over a column that repeats at a finer grain (header values on order lines, e.g. `Freight` per order stored on every line), measures over M:M relationships, DISTINCTCOUNT expected but SUM used, ratios that average percentages instead of dividing totals.
**Fix:** aggregate at the right grain (`SUMX ( VALUES ( Sales[OrderID] ), CALCULATE ( MAX ( Sales[Freight] ) ) )`) or move the value to its own table.

### DAX103 · Time intelligence without a proper date table · 🟠 High `[J]`
If a measure uses `SAMEPERIODLASTYEAR`, `DATESYTD`, `DATEADD`, etc., confirm the date column belongs to a marked, contiguous calendar related to the fact (see MOD004). Using a fact date column or an auto date table gives gaps and wrong prior periods.

### DAX104 · Complex expression without variables · 🔵 Low (🟡 Medium if a sub-expression repeats 3+ times) `[J]`
**Why:** a repeated sub-expression is evaluated again each time (often), and the measure is hard to read and debug.
**Bad:** `CALCULATE ( [Total Sales], SAMEPERIODLASTYEAR ( 'Date'[Date] ) )` written three times.
**Good:**
```dax
Sales Growth % =
VAR SalesPY = CALCULATE ( [Total Sales], SAMEPERIODLASTYEAR ( 'Date'[Date] ) )
RETURN DIVIDE ( [Total Sales] - SalesPY, SalesPY )
```

### DAX105 · One KPI, several formulas · 🟡 Medium `[J]`
Look for: measures with different names that compute the same business number differently (`[Total Sales] = SUMX(Sales, Qty * Price)` vs `[Sales Amount] = SUM(Sales[Line Total])`), or the same name in different tables. Two numbers for "sales" will disagree on some page and destroy trust.
**Fix:** one base measure; others reference it.

### DAX106 · Semantic change in a PR · 🟠 High `[J]`, PR mode only
For each **modified** measure in `scope.json`, compare old and new expressions (`git show <mergeBase>:<file>`). Does the change alter results for the **impacted** measures and visuals listed in `impacted`? Call out silent meaning changes (e.g. a base measure switching from gross to net) and name the impacted visuals.
