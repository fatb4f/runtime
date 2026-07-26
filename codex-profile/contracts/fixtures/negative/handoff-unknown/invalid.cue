package negative

import profile "github.com/fatb4f/dotfiles/codexprofile"

invalid: profile.#Handoff & {
	schema:     "codex.handoff.v0"
	createdAt:  "2026-07-23T12:34:56Z"
	objective:  "objective"
	invariants: []
	decisions:  []
	repository: {
		root:        "/tmp"
		revision:    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
		branch:      null
		dirtyPaths:  []
		stagedPaths: []
	}
	validation:         {passing: [], failing: [], notRun: []}
	currentOperation:   "current"
	nextOperation:      "next"
	completionCriteria: ["done"]
	evidencePointers:   []
	openQuestions:      []
	unknown:            true
}
