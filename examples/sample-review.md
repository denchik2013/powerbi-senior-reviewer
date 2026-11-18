<!--
Unedited output of one end-to-end run (eval round 2, run "bad2") on tests/fixtures/BadModel:
  claude -p "review my Power BI project" --plugin-dir <this repo>
Grade: recall 42/43 (98%), all 56 citations point to real file:line. The only miss was the pie chart by product name (RPT103).
Known slip kept as-is: the Notes say `out/` is not git-ignored; it was (SKILL.md now tells the reviewer how to check).
-->

# Power BI review: BadModel

**Health score: 46/100** · Full review · 2026-11-18

| Model | DAX | Power Query | Report | Security | Governance |
|:-:|:-:|:-:|:-:|:-:|:-:|
| 5 | 26 | 56 | 84 | 66 | 97 |

The numbers on this report can't be trusted yet. "Revenue" counts rows, average order value is weighted by line count, and budget can't be sliced by anything but category. A database password is committed in M code, and row-level security is one hard-coded e-mail address.

## Fix these first
1. **Rotate and remove the ODBC password** · `BadModel/BadModel.SemanticModel/definition/tables/Product.tmdl:39` · it is readable by anyone with the repo and stays in git history.
2. **`[Total Revenue]` is `COUNTROWS`** · `.../tables/Sales.tmdl:15` · a row count is shown as `$12,431`.
3. **RLS is one hard-coded e-mail and leaves FactBudget and Customer contact data exposed** · `.../roles/Regional Managers.tmdl:4`.

(All paths below are relative to `BadModel/BadModel.SemanticModel/definition/` unless they start with `BadModel.Report`.)

## Findings

### 🔴 Critical
#### PQ002 · Credential in M code
**Where:** `tables/Product.tmdl:39` · Product partition
```m
Source = Odbc.DataSource("dsn=Inventory;uid=report_user;pwd=***", [HierarchicalNavigation=true]),
```
**Why it matters:** the password is in the PBIP and in git history, so removing it from the file is not enough.
**Fix:** use a DSN or gateway data source with stored credentials, `Odbc.DataSource("dsn=Inventory", [HierarchicalNavigation=true])`. Rotate the `report_user` password and purge it from history. I did not touch history.

### 🟠 High
#### DAX101 · `Total Revenue` counts rows
**Where:** `tables/Sales.tmdl:15` · `Sales[Total Revenue]`
```dax
measure 'Total Revenue' = COUNTROWS(Sales)
```
**Why it matters:** the `\$#,0` format makes a line count look like money. Confirm the intended definition before I change it.
**Fix:**
```dax
measure 'Total Revenue' = [Total Sales]
```

#### DAX102 · `Avg Order Value` is averaged per line, not per order
**Where:** `tables/Sales.tmdl:31`
```dax
AVERAGEX(
    Sales,
    SUMX(
```
**Why it matters:** `AVERAGEX(Sales, …)` visits each order line, so a 10-line order counts ten times. The result also leans on `EARLIER`.
**Fix:**
```dax
measure 'Avg Order Value' = DIVIDE([Total Sales], DISTINCTCOUNT(Sales[OrderID]))
```

#### MOD103 · Budget is many-to-many on Category only
**Where:** `relationships.tmdl:23` · FactBudget → Product
```tmdl
relationship 5b1f0000-0000-4000-8000-000000000006
	fromCardinality: many
	toCardinality: many
```
**Why it matters:** budget has no link to Date or Store. `[Budget vs Actual]` (`tables/FactBudget.tmdl:8`, `= [Total Sales] - [Budget Amount]`) subtracts a full-year, all-store budget from sales filtered by period or store.
**Fix:** add a Category dimension and a month key to FactBudget and relate both as many-to-one. Then compare at month × category grain.

#### CUS007 · Bi-directional relationship with no reason (overrides MOD001)
**Where:** `relationships.tmdl:2` · Sales → Customer
```tmdl
crossFilteringBehavior: bothDirections
```
**Why it matters:** this creates ambiguity and lets the store RLS filter prune the Customer list (see SEC101).
**Fix:** delete the line, or document it with `annotation BidiReason = <why>`.

#### CUS009 · RLS hard-codes an e-mail (overrides SEC002)
**Where:** `roles/Regional Managers.tmdl:4`
```tmdl
tablePermission dim_store = 'dim_store'[Manager Email] = "anna.kowalski@contoso.com"
```
**Why it matters:** the role works for one person. Everyone else assigned to it sees no stores, and every change means editing the model.
**Fix:**
```tmdl
tablePermission Security = [UserPrincipalName] = USERPRINCIPALNAME()
```
Use a hidden `Security` table (`UserPrincipalName`, `StoreKey`) related to `dim_store[StoreKey]`.

#### SEC101 · The role does not cover all the data
**Where:** `roles/Regional Managers.tmdl:4`
```tmdl
tablePermission dim_store = 'dim_store'[Manager Email] = "anna.kowalski@contoso.com"
```
**Why it matters:** the filter reaches Sales only. FactBudget hangs off Product and is fully visible. `Customer[Email]` and `Customer[Phone]` (`tables/Customer.tmdl:20,26`) are visible, and the bi-directional link in `relationships.tmdl:2` interacts with the role.
**Fix:** filter FactBudget by store or region too, and restrict the two contact columns with object-level security.

#### MOD003 / MOD004 · No marked date table
**Where:** `model.tmdl:11` and `tables/Date.tmdl:1`
```tmdl
annotation __PBI_TimeIntelligenceEnabled = 1
table Date
```
**Why it matters:** `Date` has no `dataCategory: Time` and no key column, and the model is still using an auto `LocalDateTable` (`relationships.tmdl:29`). `Sales Growth %` and `Sales 2023` depend on these. A `Date` table that is not marked can silently return wrong time-intelligence results.
**Fix:** mark `Date` as the date table on `Date[Date]`, disable auto date/time, and drop the `LocalDateTable_…` relationship.

#### DAX001 · Filter on a whole table
**Where:** `tables/Sales.tmdl:27`
```dax
measure 'Bulk Sales' = CALCULATE([Total Sales], FILTER(Sales, Sales[Quantity] > 10))
```
**Fix:** `CALCULATE([Total Sales], Sales[Quantity] > 10)`

### 🟡 Medium
#### DAX104 · Repeated prior-year calculation
**Where:** `tables/Sales.tmdl:56` · `Sales Growth %`
```dax
CALCULATE([Total Sales], SAMEPERIODLASTYEAR('Date'[Date])) = 0,
```
The calculation appears three times (lines 56, 58, 59).
**Fix:**
```dax
VAR _py = CALCULATE([Total Sales], SAMEPERIODLASTYEAR('Date'[Date]))
RETURN DIVIDE([Total Sales] - _py, _py)
```

#### DAX105 · Two formulas for sales
**Where:** `tables/Sales.tmdl:8` · `measure 'Sales Amount' = SUM(Sales[Line Total])`, next to `Total Sales` at line 4.
**Fix:** keep one, since the two can drift apart. Also see CUS008 below.

#### Other medium findings
- **DAX002** (`tables/Sales.tmdl:19,23,59`): use `DIVIDE` in place of `/` and `IFERROR`. `avg_price` also hides errors with `IFERROR(…, 0)` (DAX003).
- **DAX006** (`tables/Sales.tmdl:34`): nested iterator.
- **DAX007** (`tables/Sales.tmdl:42,46`): hard-coded year `2023` and customer `"Contoso Ltd"`.
- **DAX009** (`BadModel.Report/definition/pages/ReportSection1/visuals/qtyByRegion/visual.json:13`): implicit aggregation of `Sales[Quantity]`.
- **MOD002 / MOD012** (`relationships.tmdl:23,19`): ambiguous path through the many-to-many link, and the inactive `ShipDate` relationship has no `USERELATIONSHIP` measure.
- **MOD005 / MOD006**: the key column `customer_code` is text and the keys are visible (`tables/Sales.tmdl:85-119`).
- **MOD008** (`tables/Sales.tmdl:78,151`): `OrderDateTime` and `TransactionGUID` are high-cardinality.
- **CUS008 / MOD009** (`tables/Sales.tmdl:157`): `column 'Line Total' = Sales[Quantity] * Sales[Unit Price]` is a calculated column on a fact table. Remove it and have Sales Amount use `[Total Sales]`.
- **PQ001**: local and UNC sources will not refresh in the service. `tables/Sales.tmdl:166` (`C:\Users\jdoe\…`), `tables/FactBudget.tmdl:35` (`C:\Finance\…`), `tables/dim_store.tmdl:33` (`\\fileserver01\…`) and `tables/Customer.tmdl:54`. Move them to SharePoint or a gateway data source.
- **RPT001** (`BadModel.Report/definition/pages/ReportSection1/page.json:4`): 17 visuals on one page. RPT005: 7 slicers on the same page.
- **RPT006** (`…/customerTable/visual.json:111`): hidden filter on `Customer[Segment]`.
- **SEC001** (`tables/Customer.tmdl:20`): visible PII columns `Email` and `Phone`.

### 🔵 Low
- **CUS006 / DAX004 / DAX005** · 13 visible measures have no description, e.g. `tables/Customer.tmdl:4`. `Total Cost` (`tables/Sales.tmdl:12`) has no format string. Add `///` descriptions and a `formatString`.
- **CUS001 / GOV002** · 16 measures sit on 3 tables with no `displayFolder` (`tables/Customer.tmdl:4`). Move them to `_Measures`.
- **CUS004 / GOV003** · `dim_store`, `avg_price` and `customer_code` are not business-friendly names. Rename to `Store`, `Average Price`, `Customer Key`.
- **CUS005** · `Sales Growth %` (`tables/Sales.tmdl:54`) should be `Sales YoY %`, and `Sales 2023` is a one-year hack.
- **MOD007 / MOD010 / MOD011** · `summarizeBy: sum` on `Date[Year]` and keys, unused columns (`Customer[Fax]`, `Product[Legacy Code]`), and `double` for money.
- **PQ003 / PQ004** · `Table.Buffer` at `tables/Customer.tmdl:56` and a second type step at `tables/Sales.tmdl:171`.
- **RPT002 / RPT003 / RPT004** · inconsistent visual formatting, auto or hidden titles, and a hidden page `ReportSection3`.

### ⚪ Nit
- **DAX008** `tables/Sales.tmdl:50`: `ALL(Sales)` where `ALLSELECTED` or `ALL` of a key column may be intended.
- **DAX010** `tables/Sales.tmdl:65`: `Discount Rate (old)` is unused.

## What's good
- `Date` has a proper sort-by column for `Month` (`tables/Date.tmdl:22`), so month charts sort chronologically.
- Measures are built on one base `[Total Sales]`, so changes to the base flow to the derived measures.
- `Total Sales`, `Margin %` and `Sales % of Total` have clear names and percent formats.
- A `ShipDate` role-playing relationship exists (inactive), so the model is structurally prepared for ship-date analysis.

## Notes
- The `out/` folder is not git-ignored in this repo. Add it to `.gitignore` if you don't want to commit it.
- I did not review the Power Query steps beyond the static rules or open the PBIR visuals beyond the cited lines.
- Static checks: 48 findings. 2 are recorded as dropped in `out/judgment.json` (MOD001 superseded by CUS007, SEC002 by CUS009). The rest are kept as reported or merged into the groups above, and I added 9 judgment findings. I only spot-checked the low and nit static findings.
