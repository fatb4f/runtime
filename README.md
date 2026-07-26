## Strategy adopted

Created **[#84 — Build the redistributable uv Codex runtime through partition-first POC layers](https://github.com/fatb4f/dotfiles/issues/84)**.

The implementation target is now explicitly:

```text
SourcePartition(runtime)
├── runtime kernel
├── uv-native projection integrations
├── runtime/environment provenance
├── CUE evaluation boundary
├── DuckDB catalog
├── Repository BOM producer
└── marimo operator surface

SourcePartition(subject)
└── dotfiles — later observed fixture
```

## Prototype order

1. **Runtime bootstrap and self-description**

   - Deterministic `repo-runtime describe`
   - PEP 621 identity, uv lock, schema and adapter inventory

2. **Partition kernel**

   - Embedded and external runtime fixtures
   - Containment, opacity and cross-partition relationship rules

3. **Projection integration kernel**

   - Convert the existing uv producer into the first #83-conforming integration

4. **Runtime self-projection**

   - Generate a runtime-only `ProducerProjection[]`
   - Admit and publish a runtime-only CycloneDX BOM

5. **DuckDB and marimo**

   - Private, single-writer runtime catalog
   - Read/reactive marimo surface without implicit mutations

6. **CUE façade**

   - Subprocess reference implementation
   - Narrow gopy boundary only after differential equivalence

7. **Redistribution witness**

   - Embedded source
   - External runtime checkout
   - Installed runtime distribution

8. **Subject repository POC**

   - Introduce dotfiles as a separate surface and subject partition

9. **Capability expansion**

   - Jujutsu
   - Python Git object projection
   - gmeta
   - language projection integrations
   - optional Syft inventory

## Issue alignment

Added strategy amendments to:

- **#63:** runtime-first vertical POCs now govern implementation sequencing.
- **#81:** existing work becomes the bootstrap runtime-partition implementation.
- **#83:** uv is the first projection integration; broad adapter implementation is deferred.
- **#82:** runtime provenance initially describes the runtime partition itself.
- **#67:** checkpoint binding waits for an admitted redistributable runtime realization.

The key release gate is now:

```text
runtime source partition
        ↓
uv/Python projection integrations
        ↓
ProducerProjection[]
        ↓
CUE admission
        ↓
runtime Repository BOM
        ↓
external/installable runtime witness
```

The full VCS–blob–metadata model is no longer a prerequisite for proving the runtime architecture.
