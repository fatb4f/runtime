package contextmodel

// rootSeed is the temporary authoritative data seed for the reactive workbook.
rootSeed: #ContextModel & {
	migration: {
		replacementRequires: [
			"fixture_parity",
			"projection_parity",
			"authority_mapping",
			"workbook_parity",
		]
	}
	inventory: {
		fragments: {
			"resolver.lifecycle": {
				summary: "Resolver lifecycle, bounded context, and generated-output constraints."
				sourceRef: path: ".codex/plugins/agent-context-resolver/SKILL.md"
				prerequisites: []
				authority: {
					semanticRole:   "constraint"
					artifactClass:  "source"
					claimAuthority: "root"
					sourceRef: path: ".codex/plugins/agent-context-resolver/SKILL.md"
				}
			}
			"resolver.context-workbook": {
				summary: "Canonical Marimo reactive DAG and DSPy context-establishment program."
				sourceRef: path: ".codex/context-workbook/context-workbook.py"
				prerequisites: ["resolver.lifecycle"]
				authority: {
					semanticRole:   "workflow"
					artifactClass:  "source"
					claimAuthority: "root"
					sourceRef: path: ".codex/context-workbook/context-workbook.py"
				}
			}
			"resolver.prompt-routing": {
				summary: "Legacy lexical route projection retained only as migration evidence."
				sourceRef: path: ".codex/plugins/agent-context-resolver/generated/prompt_routes.json"
				prerequisites: ["resolver.lifecycle"]
				authority: {
					semanticRole:   "evidence"
					artifactClass:  "generated_projection"
					claimAuthority: "none"
					sourceRef: path: ".codex/plugins/agent-context-resolver/generated/prompt_routes.json"
				}
			}
			"code-intel.provider-routing": {
				summary: "Read-only path, language, provider, and overlay routing evidence."
				sourceRef: path: ".codex/plugins/code-intel/reference/lsp/provider-routing.json"
				prerequisites: []
				authority: {
					semanticRole:   "evidence"
					artifactClass:  "generated_projection"
					claimAuthority: "none"
					sourceRef: path: ".codex/plugins/code-intel/reference/lsp/provider-routing.json"
				}
			}
		}
		providers: {
			"cue-lsp": {
				kind:         "lsp"
				languages:    ["cue"]
				pathGlobs:    ["**/*.cue"]
				evidenceOnly: true
				authority: {
					semanticRole:   "evidence"
					artifactClass:  "generated_projection"
					claimAuthority: "none"
				}
			}
			"lua-language-server": {
				kind:      "lsp"
				languages: ["lua"]
				pathGlobs: [
					"chezmoi/private_dot_config/nvim/**/*.lua",
					"chezmoi/private_dot_config/wezterm/**/*.lua",
				]
				evidenceOnly: true
				authority: {
					semanticRole:   "evidence"
					artifactClass:  "generated_projection"
					claimAuthority: "none"
				}
			}
			"mcp-tool-registry": {
				kind:         "mcp"
				languages:    []
				pathGlobs:    [".codex/plugins/code-intel/reference/mcp/*.json"]
				evidenceOnly: true
				authority: {
					semanticRole:   "evidence"
					artifactClass:  "generated_projection"
					claimAuthority: "none"
				}
			}
		}
		workflows: {
			"context-establishment": {
				summary: "Materialize evidence, establish hypotheses, detect gaps and conflicts, evaluate sufficiency, and project bounded context."
				steps: [
					{id: "materialize", dependsOn: []},
					{id: "hypothesize", dependsOn: ["materialize"]},
					{id: "detect-gaps", dependsOn: ["hypothesize"]},
					{id: "detect-conflicts", dependsOn: ["hypothesize"]},
					{id: "evaluate-sufficiency", dependsOn: ["detect-gaps", "detect-conflicts"]},
					{id: "project-context", dependsOn: ["evaluate-sufficiency"]},
				]
				authority: {
					semanticRole:   "workflow"
					artifactClass:  "source"
					claimAuthority: "root"
				}
			}
			"lua-first": {
				summary: "Resolve declared Lua entrypoints and type overlays before generic repository context."
				steps: [
					{id: "collect-entrypoints", dependsOn: []},
					{id: "load-overlays", dependsOn: ["collect-entrypoints"]},
					{id: "route-provider", dependsOn: ["load-overlays"]},
				]
				authority: {
					semanticRole:   "workflow"
					artifactClass:  "generated_projection"
					claimAuthority: "candidate"
				}
			}
		}
	}
	projections: {
		"agent-context-resolver": {
			kind:         "agent_context_resolver"
			packageRoot:  ".codex/plugins/agent-context-resolver"
			outputSchema: "agent.resolver-prompt-surface.v2"
			browserless:  true
			authority: {
				semanticRole:   "workflow"
				artifactClass:  "generated_projection"
				claimAuthority: "none"
			}
		}
		"code-intel": {
			kind:         "code_intel"
			packageRoot:  ".codex/plugins/code-intel"
			outputSchema: "dotfiles.code-intel-context.v0"
			browserless:  true
			authority: {
				semanticRole:   "evidence"
				artifactClass:  "generated_projection"
				claimAuthority: "none"
			}
		}
	}
}
