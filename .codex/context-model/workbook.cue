package contextmodel

// WorkbookConfig is provisional CUE authority for bounded runtime materialization.
#WorkbookConfig: close({
	schema: "dotfiles.context-workbook-config.v0"
	allowedPaths: [...#Path] & [_, ...]
	codeIntelFiles: [...#Path] & [_, ...]
	limits: close({
		maxSelectedFiles: int & >0 & <=128
		maxPacketBytes:   int & >=1024 & <=1048576
	})
	reasoning: close({
		engine:          "dspy"
		canonicalDAG:    #Path
		browserlessPath: #Path
		lexicalFallback: false
	})
})

workbookConfig: #WorkbookConfig & {
	schema: "dotfiles.context-workbook-config.v0"
	allowedPaths: [
		".codex/context-model",
		".codex/context-workbook",
		".codex/plugins/agent-context-resolver",
		".codex/plugins/code-intel",
		"chezmoi/private_dot_config/nvim",
		"chezmoi/private_dot_config/wezterm",
	]
	codeIntelFiles: [
		".codex/plugins/code-intel/reference/lsp/provider-routing.json",
		".codex/plugins/code-intel/reference/mcp/tool-registry.json",
		".codex/plugins/code-intel/reference/workflows/lua-first/workflow.json",
	]
	limits: {
		maxSelectedFiles: 32
		maxPacketBytes:   65536
	}
	reasoning: {
		engine:          "dspy"
		canonicalDAG:    ".codex/context-workbook/context-workbook.py"
		browserlessPath: ".codex/context-workbook/workbook_cli.py"
		lexicalFallback: false
	}
}
