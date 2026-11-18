# Expected issues

What a good review of the fixtures must find. Used by `tests/eval/grade.py` to measure recall on **BadModel** and
false positives on **GoodModel** (see `docs/EVALS.md`).

**Kind:** **S** = static (found by `static_checks.py`; the reviewer must keep it, not drop it), **J** = judgment (only
the reviewer can find it: wrong logic, wrong grain, security reach, chart choice).

**Matching:** an issue counts as found when one kept finding (static findings not dropped in `judgment.json`, plus the
judgment findings) has one of the accepted rule ids **and** the anchor regex (case-insensitive) matches its object, file,
title, evidence or message. `CUS` ids are accepted where a team rule supersedes the general rule.

## BadModel (43 planted issues)

Paths are relative to `tests/fixtures/BadModel/BadModel.SemanticModel/definition/` (model) or
`tests/fixtures/BadModel/BadModel.Report/definition/pages/` (report).

| ID | Kind | Rules accepted | Anchor | Where | What is planted |
|---|---|---|---|---|---|
| B01 | S | PQ002 | `Product` | `tables/Product.tmdl:39` | ODBC connection string with a password in the M source |
| B02 | J | DAX101 | `Total Revenue` | `tables/Sales.tmdl:15` | `[Total Revenue] = COUNTROWS(Sales)` formatted as `$`: counts rows, shown as money on the Overview card |
| B03 | J | DAX105 | `Sales Amount\|Total Sales` | `tables/Sales.tmdl:4,8` | `[Total Sales]` (SUMX qty × price) and `[Sales Amount]` (SUM of calc column, no `$`) are the same KPI with two formulas |
| B04 | S | DAX006 | `Avg Order Value` | `tables/Sales.tmdl:30` | Nested iterators with FILTER/EARLIER over the fact table |
| B05 | J | DAX102\|DAX101 | `Avg Order Value` | `tables/Sales.tmdl:30` | AVERAGEX over *lines* of the order total: the average is weighted by line count, not by order |
| B06 | J | MOD103\|DAX102\|MOD101 | `Budget` | `tables/FactBudget.tmdl:1`, `ReportSection2/visuals/budgetByProduct` | Budget at Category × Month grain sliced by Product Name: every product repeats its category budget |
| B07 | S | MOD002 | `FactBudget` | `relationships.tmdl:23` | Many-to-many relationship FactBudget[Category] → Product[Category] |
| B08 | J | SEC101 | `.` | `roles/Regional Managers.tmdl:4` | The role filters `dim_store` only: FactBudget has no path from `dim_store`, and Customer (with e-mail/phone) is not filtered because the bi-directional relationship does not apply security filters in both directions, so both stay fully visible to every regional manager |
| B09 | S | SEC002\|CUS009 | `Regional\|dim_store` | `roles/Regional Managers.tmdl:4` | RLS with a hard-coded e-mail |
| B10 | S | SEC001 | `Customer\|Email\|Phone` | `tables/Customer.tmdl:20` | Customer e-mail and phone visible with no RLS / OLS |
| B11 | S | MOD001\|CUS007 | `customer_code\|Customer` | `relationships.tmdl:2` | Bi-directional Sales → Customer relationship |
| B12 | S | MOD005\|CUS003 | `customer_code` | `relationships.tmdl:1` | Relationship on a text key |
| B13 | S | MOD003 | `.` | `model.tmdl:11` | Auto date/time enabled (LocalDateTable present) |
| B14 | S | MOD004\|DAX103 | `Date` | `tables/Date.tmdl:1` | Date table not marked as a date table while time intelligence is used |
| B15 | S | MOD012 | `ShipDate` | `relationships.tmdl:19` | Inactive ShipDate relationship that no measure activates |
| B16 | S | MOD008 | `OrderDateTime` | `tables/Sales.tmdl:78` | Date-time with time part (high cardinality) |
| B17 | S | MOD008 | `TransactionGUID` | `tables/Sales.tmdl:151` | GUID column imported into the model |
| B18 | S | MOD009\|CUS008 | `Line Total` | `tables/Sales.tmdl:157` | Row-level calculated column on the fact table |
| B19 | S | MOD011 | `.` | `tables/FactBudget.tmdl:26` | Money columns stored as Double |
| B20 | S | MOD010 | `.` | `tables/Customer.tmdl:32` | Unused columns (Fax, Legacy Code, Region, Month) |
| B21 | S | DAX001 | `Bulk Sales` | `tables/Sales.tmdl:27` | `FILTER(Sales, …)` as a CALCULATE filter |
| B22 | S | DAX002 | `Margin %` | `tables/Sales.tmdl:19` | Division with `/` |
| B23 | S | DAX003 | `avg_price` | `tables/Sales.tmdl:23` | IFERROR hides errors |
| B24 | S | DAX007 | `Sales 2023\|Contoso` | `tables/Sales.tmdl:42,46` | Hard-coded year and customer in measures |
| B25 | J | DAX104 | `Sales Growth` | `tables/Sales.tmdl:59` | PY expression repeated three times without VAR |
| B26 | S | DAX004\|CUS006 | `Total Cost\|format` | `tables/Sales.tmdl:12` | Measure without a format string |
| B27 | S | DAX010 | `Discount Rate` | `tables/Sales.tmdl:65` | Unused measure |
| B28 | S | DAX009\|CUS002 | `Quantity\|qtyByRegion` | `ReportSection1/visuals/qtyByRegion/visual.json:13` | Implicit "Sum of Quantity" in a visual |
| B29 | S | PQ001 | `.` | `tables/Sales.tmdl:166` (+3) | Hard-coded paths and server names |
| B30 | S | PQ003 | `Customer\|Buffer` | `tables/Customer.tmdl:56` | Table.Buffer |
| B31 | S | PQ004 | `.` | `tables/Sales.tmdl:171` | Repeated change-type steps |
| B32 | S | RPT001\|CUS010 | `Overview` | `ReportSection1/page.json:4` | 17 data visuals on Overview |
| B33 | S | RPT005 | `.` | `ReportSection1/page.json:4` | 7 slicers on one page |
| B34 | S | RPT006 | `customerTable\|Segment\|filter` | `ReportSection1/visuals/customerTable/visual.json:111` | Hidden visual-level filter |
| B35 | J | RPT103 | `pie` | `ReportSection1/visuals/pieByProduct/visual.json:13` | Pie chart by Product Name (dozens of slices) |
| B36 | S | RPT002\|RPT003 | `.` | `ReportSection1/visuals/*` | Visuals without alt text / titles |
| B37 | S | RPT004 | `Old Draft` | `ReportSection3/page.json:4` | Hidden page nothing navigates to |
| B38 | S | GOV003\|CUS004 | `.` | `tables/Customer.tmdl:1` | Mixed naming (`dim_store`, `FactBudget`, `avg_price`, `Customer Name`) |
| B39 | S | DAX008 | `.` | `tables/Sales.tmdl:50` | ALL as a CALCULATE modifier |
| B40 | S | MOD006\|CUS003 | `.` | `tables/Sales.tmdl:85` | Visible relationship keys |
| B41 | S | MOD007 | `.` | `tables/Date.tmdl:16` | Numeric attributes that summarize by default |
| B42 | S | GOV002\|CUS001 | `.` | `tables/Customer.tmdl:4` | Measures spread over fact tables, no folders |
| B43 | S | DAX005\|CUS006 | `.` | `tables/Customer.tmdl:4` | Report measures without descriptions |

## GoodModel

No planted issues. Every kept finding counts as a false positive (target: ≤ 3). The model follows all general rules and
the default custom rules CUS001–CUS010: measures in `_Measures` with folders, descriptions and format strings; integer
hidden `<Entity>Key` columns; marked date table; parameterised sources; RLS through a hidden `Security` table with
`USERPRINCIPALNAME()`; no personal-data columns imported; an 8-visual overview page with titles and alt text.
