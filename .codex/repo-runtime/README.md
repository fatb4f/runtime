# Repository BOM runtime

This contained Python 3.12+ uv project implements the first portable slice of
Issue #81. It derives Git repository state and uv resolution observations,
admits them through the Repository BOM profile, and publishes deterministic
CycloneDX 1.7 JSON.

The CycloneDX document is the only public repository-intelligence artifact.
`repo_intel` observations and `ProducerProjection` are private construction
inputs. Resolver, workbook, Codex, legacy packet, full Git realization,
environment, and direnv integration are intentionally outside this slice.

```bash
uv run --project .codex/repo-runtime repo-bom generate \
  --repository /path/to/repository \
  --output /tmp/repository.cdx.json
uv run --project .codex/repo-runtime repo-bom validate \
  /tmp/repository.cdx.json
uv run --project .codex/repo-runtime repo-bom check \
  --repository /path/to/repository \
  --expected /tmp/repository.cdx.json
```

Generation requires a Git root containing `pyproject.toml` and a consistent
`uv.lock`. Public paths are normalized repository-relative POSIX paths.
Unsupported non-uv content is explicitly unclassified; it does not fail the uv
slice.
