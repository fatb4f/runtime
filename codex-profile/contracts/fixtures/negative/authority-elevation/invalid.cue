package negative

import profile "github.com/fatb4f/dotfiles/codexprofile"

invalid: profile.#Provenance & {
	authority: "explicit_checkpoint"
	source: {
		source: {
			kind:       "rollout"
			sourceID:   "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
			generation: 0
		}
		sourceOffset: 0
	}
}
