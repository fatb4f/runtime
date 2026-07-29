set shell := ["bash", "-euo", "pipefail", "-c"]

promptgen *args:
    uv run bash scripts/promptgen {{args}}

handoffgen *args:
    uv run handoff create {{args}}

bundle:
    uv build --wheel --out-dir dist --clear
