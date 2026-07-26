# Dotfiles context workbook

This directory is the canonical executable program for Issue #54.

- `.codex/context-model` is the provisional CUE authority.
- `context-workbook.py` is the Marimo reactive DAG.
- `context_workbook.dspy_program.DspyContextProgram` performs context inference.
- `workbook_cli.py` executes the same DAG without a browser.
- recorded decisions are accepted only with `CONTEXT_WORKBOOK_TEST_MODE=1`.
- missing DSPy configuration produces a typed blocking gap; it never activates the removed lexical classifier.
- repository inputs are read from the immutable commit resolved by the request revision.
- request-file paths and projection IDs may narrow, but never widen, the CUE workbook configuration.

## Bootstrap

```sh
uv sync
```

Production execution defaults to `codex/gpt-5.6-sol`; the Codex CLI reuses its cached ChatGPT login.
`CONTEXT_WORKBOOK_DSPY_MODEL` may override the model. Direct API-backed DSPy models require their
provider credentials, while `codex/*` models require an authenticated Codex CLI session.
`CONTEXT_WORKBOOK_CODEX` may select a specific Codex executable.
Installed resolver adapters discover the workbook from the active Git worktree; automation may set
`CONTEXT_WORKBOOK_REPO_ROOT` explicitly when the invocation directory is outside that worktree.

## Validation

```sh
bash .github/scripts/context-workbook-test.sh
```

## Projection regeneration

```sh
uv run -- \
  python -m context_workbook.projections --repo-root .
```

## Evidence-edge containment

The v0 workbook projection permits one evidence ID per hypothesis, selection, conflict, or evidence-to-observation edge. Multiple independent claims are represented as multiple typed nodes. This keeps every reactive edge independently invalidatable while remaining a valid subtype of the broader CUE root model.
