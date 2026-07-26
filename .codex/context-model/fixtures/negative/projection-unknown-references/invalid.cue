package projectionunknownreferences

import positive "github.com/fatb4f/dotfiles/context-model/fixtures/positive:positive"

invalid: positive.base & {
	projection: {
		schema:        "dotfiles.context-packet.v0"
		requestID:     "issue-54"
		contextDigest: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
		selected: {
			fragmentIDs: ["fragment.unknown"]
			files:       [".codex/context-model/model.cue"]
			providerIDs: ["provider.unknown"]
			workflowIDs: ["workflow.unknown"]
		}
		evidenceIDs:      ["evidence.unknown"]
		unresolvedGapIDs: ["gap.unknown"]
		provenance: {
			semanticRole:   "workflow"
			artifactClass:  "generated_projection"
			claimAuthority: "candidate"
		}
	}
}
