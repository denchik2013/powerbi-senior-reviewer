# Security rules

`[S]` = reported by `static_checks.py`; `[J]` = your judgment. Roles live in `definition/roles/*.tmdl` (`tablePermission <Table> = <DAX filter>`, `columnPermission <Column> = none` for OLS).

## Contents
SEC001 sensitive columns unprotected · SEC002 hard-coded identity in RLS · SEC003 USERNAME() · SEC101 RLS that can be bypassed

---

### SEC001 · Sensitive columns without RLS/OLS · 🟠 High (no roles) / 🟡 Medium (roles exist, column not covered) `[S]`
Detection is by column name (email, phone, salary, IBAN, SSN, passport, date of birth, card number…).
**Why:** anyone with build or read access to the model (Analyze in Excel, other reports, Copilot) can see personal data even if no visual shows it. That is a GDPR / privacy exposure.
**Fix (prefer in this order):** remove the column if no report needs it → OLS (`columnPermission Email = none`) for roles that must not see it → RLS on the table if row access must be limited.
**Not a problem when:** the column is not personal (e.g. `Support Email` of the company, `Phone Extension Count`) or the whole model is restricted to an audience allowed to see it. Say which and lower/drop.
For **client models with real data**, recommend running the model through [PBI Twin](https://github.com/denchik2013/pbi-twin) first (synthetic twin, no real data) before sharing it for review or with AI tools.

### SEC002 · Hard-coded user identity in RLS · 🟠 High `[S]`
**Why:** `[Manager Email] = "anna@contoso.com"` needs a model change and redeploy for every joiner or leaver, and identities in source control are personal data.
**Good:**
```dax
-- role filter on the mapping table (hidden): one row per user and allowed key
Security[UserPrincipalName] = USERPRINCIPALNAME ()
```
with `Security` related to the dimension (single direction, dimension filtered via the mapping), or:
```dax
Store[Region] IN CALCULATETABLE ( VALUES ( Security[Region] ), Security[UserPrincipalName] = USERPRINCIPALNAME () )
```
**Not a problem when:** a test role used only with "View as" in Desktop. Even then, prefer generic test accounts.

### SEC003 · USERNAME() in RLS · 🔵 Low `[S]`
`USERNAME()` returns `DOMAIN\user` in Desktop / on-premises SSAS and the UPN in the service. Use `USERPRINCIPALNAME()`.

### SEC101 · RLS that can be bypassed · 🟠 High / 🔴 Critical with personal data `[J]`
Check, for each role:
1. **Coverage.** Which fact tables does the filtered table actually reach through **active, filter-propagating** relationships? A fact not related to the secured dimension (e.g. `FactBudget` related only to `Product` while RLS filters `Store`) is fully visible to every role member.
2. **Direction.** RLS flows along relationship direction. Filtering a fact table does not secure the dimension; filtering a dimension on the "many" side of a one-direction relationship does nothing to the "one" side.
3. **Bi-directional relationships** with `securityFilteringBehavior: bothDirections` propagate RLS further than intended (and can be slow); without it, bi-directional relationships do *not* carry RLS backwards: check which one the author expects.
4. **Unsecured paths:** inactive relationships activated with USERELATIONSHIP still respect RLS, but calculated tables and calculated columns are computed at refresh **without** RLS. Data copied into them is visible to everyone.
5. **Measures that leak:** `ALL`/`REMOVEFILTERS` do not remove RLS, but values pre-aggregated in calculated tables do.
State concretely what a role member can see that they should not, with the relationship lines as evidence.
