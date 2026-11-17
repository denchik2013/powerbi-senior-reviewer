---
name: powerbi-senior-reviewer
description: Senior-level code review of Power BI projects and pull requests (PBIP with TMDL semantic model and PBIR report). Runs offline deterministic checks, then adds expert judgment such as measures whose logic contradicts their name, double counting, ambiguous filter paths, RLS gaps, and overloaded report pages. Produces a scored review with file:line evidence and ready-to-paste DAX/TMDL/M fixes. Use when the user asks to review, audit, or health-check a Power BI model, report, semantic model, dataset, or PBIP project; asks "is my DAX ok" or for best practices on a semantic model; asks to review a PR, branch, commit, or diff in a repository that contains *.pbip, *.SemanticModel, *.Report, .tmdl, or definition.pbir files; or shares TMDL or PBIR files and asks what is wrong with them. Not for building new reports or models from scratch.
license: MIT
compatibility: Requires Python 3.10+ (standard library only) and git for PR mode. No network access.
metadata:
  version: "0.1.0"
  repository: https://github.com/denchik2013/powerbi-senior-reviewer
---

# Power BI Senior Reviewer

Work in progress. The review workflow lands in stage 3.
