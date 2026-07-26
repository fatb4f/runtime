package negative

import profile "github.com/fatb4f/dotfiles/codexprofile"

invalid: profile.#PolicyAssessment & {
	schema:         "codex-policy-assessment.v0"
	telemetryState: "healthy"
	recommendation: "compact"
	reasons:        ["operator requested compaction"]
	projection: {
		projectionID: "policy.v0"
		version:      "0.1.0"
		digest:       "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
	}
	advisoryOnly:          true
	blockNativeCompaction: true
}
