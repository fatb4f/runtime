package negative

import profile "github.com/fatb4f/dotfiles/codexprofile"

invalid: profile.#SourceCheckpoint & {
	sourceID:         "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	sourceGeneration: 1
	nextOffset:       128
	anchorStart:      120
	anchorEnd:        129
	anchorDigest:     "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}
