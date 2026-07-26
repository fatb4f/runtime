package claimantfield

import model "github.com/fatb4f/dotfiles/context-model:contextmodel"

invalid: model.#SourceObservation & {
	kind:    "tool"
	subject: "cue-vet"
	facts: {
		passed: true
	}
	diagnostics: []
	provenance: {
		semanticRole:   "evidence"
		artifactClass:  "runtime_observation"
		claimAuthority: "none"
	}
}
