package negative

import profile "github.com/fatb4f/dotfiles/codexprofile"

sourceA: profile.#SourceCoordinate & {
	source:       {kind: "rollout", sourceID: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", generation: 0}
	sourceOffset: 1
}
sourceB: profile.#SourceCoordinate & {
	source:       {kind: "hook_journal", sourceID: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", generation: 0}
	sourceOffset: 1
}
sourceC: profile.#SourceCoordinate & {
	source:       {kind: "checkpoint", sourceID: "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc", generation: 0}
	sourceOffset: 1
}
sourceD: profile.#SourceCoordinate & {
	source:       {kind: "wrapper_journal", sourceID: "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd", generation: 0}
	sourceOffset: 1
}

invalid: profile.#CrossSourceOrderClaim & {
	before: sourceA
	after:  sourceB
	edge: {
		from:     sourceC
		to:       sourceD
		evidence: "turn_id"
		value:    "turn-1"
	}
}
