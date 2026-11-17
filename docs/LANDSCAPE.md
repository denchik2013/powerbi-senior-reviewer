# Landscape: what already exists, and where this skill fits

Research date: 2026-11-17. Sources were the public repositories and official docs linked below.

## 1. Packaging format (Anthropic, current)

- **Agent Skill** = folder with `SKILL.md` (YAML frontmatter + markdown body) plus optional bundled files. Supporting docs are loaded on demand (progressive disclosure); scripts are *executed, not loaded*, referenced as `${CLAUDE_SKILL_DIR}/scripts/...`.
- **Frontmatter for portability.** Claude Code accepts many fields (`when_to_use`, `argument-hint`, `allowed-tools`, ...), but claude.ai upload / Skills API only accept `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`. Any other key is a hard error there, so we use only those.
  - `name`: ≤ 64 chars, lowercase letters, digits, hyphens; must not contain `claude` or `anthropic`.
  - `description`: ≤ 1024 chars, third person, "what it does + when to use it", key use case first.
- **Size.** Official guidance is "keep `SKILL.md` under 500 lines". Our spec is stricter, ~300 lines.
- **Plugin.** `.claude-plugin/plugin.json` (only `name` is required). Skills are auto-discovered from `skills/<name>/SKILL.md`.
- **Marketplace.** `.claude-plugin/marketplace.json` with `name`, `owner`, `plugins[]`. A single repo can be both marketplace and plugin via `"source": "./"`. Install:
  ```
  /plugin marketplace add denchik2013/powerbi-senior-reviewer
  /plugin install powerbi-senior-reviewer@powerbi-senior-reviewer
  ```
- **Validation.** `claude plugin validate .` (add `--strict` to fail on warnings).

Docs: [plugins reference](https://code.claude.com/docs/en/plugins-reference), [plugin marketplaces](https://code.claude.com/docs/en/plugin-marketplaces), [skills](https://code.claude.com/docs/en/skills), [Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview), [best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices).

## 2. Existing Power BI agent tooling

### Microsoft `skills-for-fabric` ([repo](https://github.com/microsoft/skills-for-fabric))
- Large official collection for Copilot CLI / Claude Code. Power BI parts: `semantic-model-authoring`, `powerbi-report-cli`; the report authoring/planning/design skills were announced at Build 2026.
- **Focus: authoring and operations.** It creates and changes models, reports, and deployments through `az rest`, the Fabric REST API, MCP servers, and npm CLIs (`@microsoft/powerbi-report-authoring-cli`, `powerbi-desktop` bridge).
- Requires a Fabric tenant / Azure login for most flows. The skills mandate a telemetry header on Fabric API calls.
- **No dedicated code-review skill.** Nothing produces a severity-ranked review of a PBIP or a PR.

### Data Goblins `power-bi-agentic-development` ([repo](https://github.com/data-goblin/power-bi-agentic-development), GPL-3.0)
- The most complete community marketplace (~14 plugins, weekly releases, frequent renames).
- Relevant overlaps:
  - `semantic-models/semantic-model`: full lifecycle (design, build, refresh, **review**). Drives work through the Tabular Editor `te` CLI first, then TOM via Power BI Desktop or MCP, then TMDL edits.
  - `reports/review-report`: report review centred on **usage and adoption** (Fabric usage-metrics APIs, audience reach, distribution), plus design and performance.
  - `tabular-editor/bpa-rules`: an interactive Q&A workflow for **authoring BPA rules**, not running a review.
  - `pbip/tmdl`, `pbip/pbir-format`: format knowledge.
- Relies on external tools (Tabular Editor CLI, `pbir` CLI, Power BI Desktop, Fabric APIs) and network access for its strongest features.

### Tabular Editor Best Practice Rules ([repo](https://github.com/TabularEditor/BestPracticeRules))
- `BPARules-standard.json` has 29 rules: Model Layout 9, Naming 6, Performance 5, DAX 4, Metadata 3, Formatting 2. There are also PowerBI, lax, and contrib variants.
- Rules are Dynamic LINQ expressions run by Tabular Editor's BPA against the TOM. It is pattern matching only: a measure's semantics, its name versus its logic, the report layer, PR scope, and fix snippets are all out of reach.
- Windows/Tabular Editor-centric. No report (PBIR) coverage.

## 3. Gap this skill fills

| Capability | MS Fabric skills | Data Goblins | TE BPA | **This skill** |
|---|---|---|---|---|
| Review a whole PBIP (model + report) in one pass | – | partly (separate skills) | model only | **yes** |
| **PR mode**: review only what changed in `git diff` | – | – | – | **yes** |
| Works fully offline, on files in a git repo | – | partly | yes (Windows app) | **yes** |
| No external tools (no TE, no Desktop, no Fabric login, no npm/pip) | – | – | – | **yes**: Python stdlib only |
| Deterministic checks with JSON output | – | via TE CLI | yes | **yes** |
| Judgment: misleading measure names, double counting, ambiguous paths, RLS bypass | – | partly | – | **yes** |
| Every finding cites `file:line` + quoted code | – | – | object name only | **yes** (enforced) |
| Health score + severity buckets + ready-to-paste fix | – | – | severity only | **yes** |
| Team-specific rules that override defaults | – | – | custom JSON | **yes** (`custom-rules.md`, plain English) |
| Measured quality (recall / false-positive evals on fixtures) | – | – | – | **yes** (`docs/EVALS.md`) |
| License | MIT | GPL-3.0 | MIT | MIT |

**Positioning in one line:** the others help you *build and operate* Power BI artifacts. This skill is the **reviewer that sits on your PR**: offline, file-and-line precise, and opinionated like a senior colleague.

## 4. Decisions taken from this research

1. **Complement, don't duplicate.** No authoring, no Fabric API, no usage metrics; the reviewer points to those tools in its notes. Report UX judgment stays light; adoption analytics are Data Goblins' territory.
2. **Trigger collision.** The Data Goblins `semantic-model` description also fires on "review"/"audit". Our description leads with *code review / PR / diff / PBIP files* and names concrete file types so routing is unambiguous.
3. **Portable frontmatter only** (`name`, `description`, `license`, `compatibility`, `metadata`) so the same folder uploads to claude.ai as a zip.
4. **Rules written in our own words.** BPA rules and Data Goblins references (GPL-3.0) are cited as inspiration in the README; no text is copied.
5. The TMDL/PBIR parser is our own, stdlib-only, with no dependency on the TE CLI or `pbir` CLI.
