package projectionfileoutsiderequest

import positive "github.com/fatb4f/dotfiles/context-model/fixtures/positive:positive"

invalid: positive.#Common & {
	selected: {
		fragments: []
		files: [{
			path:        "README.md"
			reason:      "Attempt to escape the request boundary."
			evidenceIDs: ["evidence.issue-54"]
		}]
		providers: []
		workflows: []
	}
	gaps:      {}
	conflicts: {}
	sufficiency: {
		state:                 "sufficient"
		reasons:               ["Incorrectly treats an out-of-bound file as sufficient context."]
		blockingGapIDs:        []
		unresolvedConflictIDs: []
	}
	projection: {
		schema:        "dotfiles.context-packet.v0"
		requestID:     "issue-54"
		contextDigest: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
		selected: {
			fragmentIDs: []
			files:       ["README.md"]
			providerIDs: []
			workflowIDs: []
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
