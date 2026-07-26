package negative

import profile "github.com/fatb4f/dotfiles/codexprofile"

invalid: profile.#HookCompleted & {
	schema:              "codex-hook-completed.v0"
	hookTransactionID:   "018f1234-5678-7abc-8def-0123456789ab"
	segmentID:           "018f1234-5678-7abc-8def-0123456789ac"
	sourceOffset:        10
	localSequence:       3
	completedAt:         "2026-07-22T12:00:00Z"
	elapsedMilliseconds: 2
	exitStatus:          0
	outputDisposition:   "continued"
	// Completion records cannot absorb start-only state.
	sessionID: "thread-1"
}
