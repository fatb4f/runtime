package positive

import profile "github.com/fatb4f/dotfiles/codexprofile"

handoff: profile.#Handoff & {
	schema:     "codex.handoff.v0"
	createdAt:  "2026-07-23T12:34:56.123456Z"
	objective:  "complete the MVP"
	invariants: []
	decisions:  []
	repository: {
		root:        "/tmp/repository"
		revision:    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
		branch:      null
		dirtyPaths:  []
		stagedPaths: []
	}
	validation: {
		passing: []
		failing: []
		notRun:  []
	}
	currentOperation:   "implement contracts"
	nextOperation:      "run qualification"
	completionCriteria: ["qualification passes"]
	evidencePointers:   []
	openQuestions:      []
}

result: profile.#CommandResult & {
	schema:        "codex.command-result.v0"
	exitCode:      0
	signal:        null
	truncated:     false
	relevantLines: []
	artifact:      "/tmp/manifest.json"
	sha256:        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}

manifest: profile.#CommandArtifactManifest & {
	schema:           "codex.command-artifact.v0"
	argv:             ["true"]
	workingDirectory: "/tmp"
	startedAt:        "2026-07-23T12:34:56.123456Z"
	durationSeconds:  0.1
	exitCode:         0
	signal:           null
	stdoutBytes:      0
	stderrBytes:      0
	stdoutSha256:     "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
	stderrSha256:     "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
}
