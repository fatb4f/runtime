package negative

import profile "github.com/fatb4f/dotfiles/codexprofile"

invalid: profile.#ContextWindowObservation & {
	schema:                  "codex-context-window-observation.v0"
	observationID:           "018f1234-5678-7abc-8def-0123456789ab"
	threadID:                "thread-1"
	windowNumber:            2
	firstWindowID:           {state: "observed", value: "018f1234-5678-7abc-8def-0123456789ac"}
	previousWindowID:        {state: "unavailable", reason: "legacy source"}
	windowID:                {state: "observed", value: "018f1234-5678-7abc-8def-0123456789ad"}
	identitySource:          "legacy_unavailable"
	transitionKind:          "legacyUnknown"
	replacementHistoryItems: {state: "unavailable", reason: "legacy source"}
	coordinate: {
		source:       {kind: "rollout", sourceID: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", generation: 0}
		sourceOffset: 0
	}
	adapter: {adapterID: "rollout.v0", version: "0.1.0", digest: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}
}
