# Report rules (PBIR)

`[S]` = reported by `static_checks.py`; `[J]` = your judgment. Report files: `*.Report/definition/pages/<page>/page.json` and `…/visuals/<visual>/visual.json`.
With a legacy `report.json` only page/visual counts and basic fields are available: say so in the review.

## Contents
RPT001 too many visuals · RPT002 alt text · RPT003 titles · RPT004 orphan hidden page · RPT005 slicers · RPT006 hidden filters ·
RPT101 page has no single question · RPT102 inconsistent formats/colors · RPT103 wrong chart type

---

### RPT001 · More than 15 visuals on a page · 🟡 Medium `[S]`
**Why:** each visual sends at least one query, so the page loads slowly and the eye has no entry point. Shapes and text boxes are not counted.
**Fix:** 6–10 visuals that answer one question; move detail to drill-through / tooltip pages; combine KPI cards into one multi-row card or new card visual.
**Not a problem when:** a deliberate operational "wall" page that users asked for. Say so and lower to Low.

### RPT002 · Visuals without alt text · 🔵 Low `[S]`
**Why:** screen readers announce only the visual type. In many organizations accessibility is a compliance requirement.
**Fix:** Format → General → Alt text, one sentence (can be a measure for dynamic text). Slicers and decorative shapes are excluded.

### RPT003 · No meaningful title · 🔵 Low `[S]`
**Why:** the auto title ("Sum of Quantity by Region") names fields, not the insight; a hidden title leaves the reader guessing.
**Fix:** state the question: "Units sold by region, current year". Cards, slicers and decorative visuals are excluded.

### RPT004 · Hidden page nothing points to · 🔵 Low `[S]`
**Why:** dead pages still ship, confuse maintainers and sometimes expose data.
**Not a problem when:** drill-through and tooltip pages (excluded automatically), or a page reached through a bookmark or button the script could not resolve: check `visualLink` / bookmarks before keeping.

### RPT005 · More than 6 slicers on a page · 🟡 Medium `[S]`
**Fix:** keep 3–5 key slicers on the canvas; put the rest in the filter pane or a slicer panel toggled with bookmarks; consider sync slicers.

### RPT006 · Hidden visual-level filter · 🟡 Medium `[S]`
**Why:** the visual shows a subset (e.g. only "Enterprise" customers) with no visible cue, so it disagrees with the rest of the page and users lose trust.
**Fix:** unhide the filter or put the condition in the title ("Enterprise customers").
**Not a problem when:** a technical filter that removes blanks or test rows. Then it is harmless; say so.

### RPT101 · Page does not answer one question · 🟡 Medium `[J]`
Read the page name, the visual titles and fields. Can you state the page's question in one sentence for its audience (e.g. a CFO: "Are we on budget this quarter and where are we off?")? Red flags: KPIs from unrelated areas on one page, 5+ KPI cards with no comparison/target, a detail table dominating an executive page, no time context.
**Fix:** propose a concrete restructure (which visuals stay, which move to drill-through).

### RPT102 · Inconsistent number formats or colors · 🔵 Low `[J]`
Compare format strings of measures shown together (one card `#,0`, the next `$#,0.00`, percentages with different decimals), and color usage (same category in different colors across visuals, red used for a non-negative meaning).
**Fix:** align format strings at the measure level; use theme colors / a consistent color per dimension member.

### RPT103 · Chart type does not fit the data · 🟡 Medium `[J]`
Common cases:
- pie/donut with many categories (more than ~5) or by a high-cardinality field (product name) → bar chart sorted descending;
- line chart over a non-time axis (categories) → bar/column;
- a table with dozens of columns as the main visual of an overview page;
- gauges without a target;
- dual-axis charts mixing unrelated measures.
**Evidence:** quote the `visualType` line and the category field from `visual.json`.
