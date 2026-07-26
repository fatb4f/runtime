package negative

import profile "github.com/fatb4f/dotfiles/codexprofile"

invalid: profile.#DuckDBWriteRequest & {
	schema:    "codex-duckdb-write.v0"
	writer:    "hook"
	operation: "append_raw"
	runID:     "018f1234-5678-7abc-8def-0123456789ac"
}
