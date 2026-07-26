package negative

import profile "github.com/fatb4f/dotfiles/codexprofile"

invalid: profile.#CheckpointAssessment & {
	checkpointID: "018f1234-5678-7abc-8def-0123456789ab"
	freshness:    "expired"
	reasons:      ["age exceeded"]
}
