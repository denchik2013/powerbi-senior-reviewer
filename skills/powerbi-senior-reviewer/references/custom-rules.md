# Custom rules (team / author conventions)

**Always read this file.** These rules come from the people who own the models. When a custom rule conflicts with a
general rule in `rules-*.md`, **the custom rule wins**. Say so in the finding ("per team rule CUS00X").

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

> The three rules below are **examples** of the format. Replace them with your own conventions.

---

### CUS001 · All measures live in `_Measures` · Medium · Governance
**Rule:** every visible measure is defined in a table named `_Measures` (all its columns hidden), grouped with `displayFolder`.
**Why:** one place to find every KPI; no measures disappear when a fact table is replaced.
**Check:** `inventory.json` → measures where `table != "_Measures"` and `isHidden == false`.
**Bad → Good:** `table Sales / measure 'Total Sales' = …` → move it to `table _Measures`, `displayFolder: Sales`.
**Overrides:** GOV002 (stricter: applies to any model size, and the "measures on their fact table" exception does not apply).
**Exceptions:** calculation group items.

### CUS002 · Time-intelligence suffixes · Low · DAX
**Rule:** time-shifted measures end with a fixed suffix: ` PY`, ` YTD`, ` QTD`, ` MTD`, ` YoY`, ` YoY %`.
**Why:** users recognize the variant at a glance and search the field list by suffix.
**Check:** measures that use SAMEPERIODLASTYEAR / DATESYTD / DATEADD / TOTALYTD but whose name lacks the matching suffix.
**Bad → Good:** `[Last Year Sales]` → `[Sales PY]`; `[Sales Growth %]` → `[Sales YoY %]`.
**Overrides:** none (adds to GOV003).
**Exceptions:** none.

### CUS003 · Executive pages: at most 8 visuals · Medium · Report
**Rule:** pages whose name starts with `Exec` or `Overview` have at most 8 data visuals (shapes and text boxes excluded).
**Why:** leadership reads these on a laptop in a meeting; more than 8 visuals means the page has no focus.
**Check:** `inventory.json` → page visuals excluding decorative types; compare with RPT001 output.
**Bad → Good:** 17 visuals on "Overview" → 5 KPI cards + 2 trend charts + 1 breakdown; detail on drill-through.
**Overrides:** RPT001 (threshold 8 instead of 15 for these pages).
**Exceptions:** pages explicitly named `… Detail`.
