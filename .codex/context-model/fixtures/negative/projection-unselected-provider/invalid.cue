package projectionunselectedprovider

import positive "github.com/fatb4f/dotfiles/context-model/fixtures/positive:positive"

invalid: positive.base & {
	projection: {
		schema:        "dotfiles.context-packet.v0"
		requestID:     "issue-54"
		contextDigest: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
		selected: {
			fragmentIDs: ["resolver.lifecycle"]
			files:       [".codex/context-model/model.cue"]
			providerIDs: ["cue-lsp"]
			workflowIDs: ["context-establishment"]
		}
		evidenceIDs:      ["evidence.issue-54"]
		unresolvedGapIDs: []
		provenance: {
			semanticRole:   "workflow"
			artifactClass:  "generated_projection"
			claimAuthority: "candidate"
		}
	}
}
