package negative

import profile "github.com/fatb4f/dotfiles/codexprofile"

invalid: profile.#UsageObservation & {
	schema:                    "codex-usage-observation.v0"
	observationID:             "018f1234-5678-7abc-8def-0123456789ab"
	threadID:                  "thread-1"
	rolloutOrdinal:            1
	usageObservationIndex:     1
	eventTimestamp:            "2026-07-22T12:00:00Z"
	reportedInputTokens:       10
	cachedInputTokens:         11
	cacheWriteInputTokens:     0
	freshInputTokens:          0
	outputTokens:              0
	reasoningOutputTokens:     0
	totalTokens:               10
	estimatedContextPressure:  {state: "unavailable", reason: "not derived"}
	nativeActiveContextTokens: {state: "unavailable", reason: "not emitted"}
	modelContextWindow:        {state: "unavailable", reason: "not emitted"}
	coordinate:                {source: {kind: "rollout", sourceID: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", generation: 0}, sourceOffset: 0}
	adapter:                   {adapterID: "rollout.v0", version: "0.1.0", digest: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}
}
