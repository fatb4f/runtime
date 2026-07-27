set shell := ["bash", "-euo", "pipefail", "-c"]

promptgen *args:
    uv run bash scripts/promptgen {{args}}

handoffgen *args:
    uv run handoff create {{args}}
