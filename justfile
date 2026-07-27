set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# Create a Git-and-rollout handoff artifact.
handoff *args:
    uv run handoff {{args}}

# Join one handoff artifact with one GitHub slice manifest.
promptgen *args:
    uv run bash scripts/promptgen {{args}}
