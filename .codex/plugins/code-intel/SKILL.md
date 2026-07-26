---
name: dotfiles-code-intel
description: Supply typed read-only code-intelligence evidence to the canonical context workbook.
---

# Dotfiles Code Intel

This plugin is an independently installable evidence adapter. It does not establish context by itself and does not import the resolver plugin.

## Contract boundary

- The canonical workbook ingests only the declared provider-routing, tool-registry, and workflow files.
- Provider declarations, type overlays, diagnostics, MCP results, and LSP results remain evidence-only.
- The bundled CUE and gopls MCP adapters are temporary read-only evidence transports; they do not hydrate or widen the canonical graph and must be retired when the native hydrator lands.
- The plugin projection contains no prompt classifier, context synthesizer, route executor, or mutation authority.
- CUE source and dotfiles source remain authoritative at their declared repository paths.
- The dynamic `dotfiles.code-intel-context.v0` projection is produced from the same validated context state as the resolver hook packet.
- Regenerate `reference/context-workbook-projection.json` from the CUE model and workbook program; never edit it as authority.
