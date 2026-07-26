package positive

import profile "github.com/fatb4f/dotfiles/codexprofile"

quarantinePhases: ["artifact-admission", "projection", "result-admission", "publication"]

quarantines: [for phase in quarantinePhases {
	profile.#CommandQuarantine & {
		schema:            "codex.command-quarantine.v0"
		argv:              ["tool", "", "--"]
		workingDirectory:  "/tmp"
		startedAt:         "2026-07-23T12:34:56Z"
		durationSeconds:   0
		exitCode:          1
		signal:            null
		stdoutBytes:       3
		stderrBytes:       0
		stdoutSha256:      "dc51b8c96c2d745df0ea3e9f9e241af470db473e4feaa30b9fa50620c2f7f18f"
		stderrSha256:      "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
		manifestAvailable: true
		failurePhase:      phase
		failureCode:       "command.output-discarded"
		failureDetail:     "retained"
	}
}]
