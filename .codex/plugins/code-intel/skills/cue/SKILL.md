---
name: cue
description: Author, refactor, diagnose, and validate nontrivial CUE schemas, evaluators, workflows, evidence ingress, and publication projections. Use when Codex modifies CUE, encounters scope, conjunction, closure, totality, cardinality, or proof-construction failures, or needs concrete positive and negative CUE probes.
---

# CUE Authoring

Treat valid CUE as a prerequisite, not as proof that the intended contract holds.

## Use language-server evidence

Use the bundled `cue_lsp` MCP server for syntax and parse diagnostics, name resolution, navigation, references, module and package awareness, hover information, and rapid local feedback while editing.

Treat every language-server result as advisory evidence. It is not an admission gate and does not hydrate or widen the canonical context graph. A clean result does not establish semantic correctness across conditional branches, comprehensions, cardinality assumptions, evidence completeness, duplicates, workflow ordering, or application-specific proof obligations.

## Run package gates

Run these gates even when the language server reports no diagnostics:

```bash
cue fmt --check --files <changed-files>
cue vet <package>
cue vet -c <package>
```

Interpret the gates precisely: passing means the package formats, unifies, and exposes the requested concrete surface. It does not prove that incorrect evidence is rejected.

## Probe the contract

Construct the smallest concrete positive and negative inputs that exercise the changed constraint. Confirm that accepted inputs remain accepted and that each relevant malformed, incomplete, contradictory, duplicated, or out-of-order input is rejected for the intended reason.

Keep the CUE source authoritative. Do not encode a second semantic model in MCP results, generated projections, or explanatory prose.
