package positive

import profile "github.com/fatb4f/dotfiles/codexprofile"

Source=source: profile.#SourceIdentity & {
	kind:       "rollout"
	sourceID:   "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	generation: 0
}

Coordinate=coordinate: profile.#SourceCoordinate & {source: Source, sourceOffset: 128}

checkpoint: profile.#SourceCheckpoint & {
	sourceID:         Source.sourceID
	sourceGeneration: Source.generation
	nextOffset:       256
	anchorStart:      192
	anchorEnd:        256
	anchorDigest:     "sha256:9999999999999999999999999999999999999999999999999999999999999999"
}

Adapter=adapter: profile.#AdapterIdentity & {
	adapterID: "rollout.v0"
	version:   "0.1.0"
	digest:    "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}

raw: profile.#RawObservationEnvelope & {
	schema:        "codex-raw-observation.v0"
	observationID: "018f1234-5678-7abc-8def-0123456789aa"
	coordinate:    Coordinate
	observedAt:    "2026-07-22T12:00:00Z"
	mediaType:     "application/json"
	rawBytes:      128
	payloadDigest: "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
	provenance: {
		authority: "upstream_observation"
		source:    Coordinate
		adapter:   Adapter
	}
	admission: {
		operation:        "append"
		deduplicationKey: Coordinate
	}
}

repository: profile.#RepositoryState & {
	repositoryID: "dotfiles"
	head: {state: "observed", value: {
		format: "sha1"
		hex:    "e535d6d69bcefbb2851eb706b41a2000cef85035"
	}}
	worktreeDigest: "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
	dirty:          false
}

usage: profile.#UsageObservation & {
	schema:                    "codex-usage-observation.v0"
	observationID:             "018f1234-5678-7abc-8def-0123456789ab"
	threadID:                  "thread-1"
	rolloutOrdinal:            4
	usageObservationIndex:     2
	eventTimestamp:            "2026-07-22T12:00:00Z"
	reportedInputTokens:       100
	cachedInputTokens:         60
	cacheWriteInputTokens:     5
	freshInputTokens:          40
	outputTokens:              10
	reasoningOutputTokens:     2
	totalTokens:               110
	estimatedContextPressure:  {state: "observed", value: 90}
	nativeActiveContextTokens: {state: "unavailable", reason: "not emitted by rollout"}
	modelContextWindow:        {state: "observed", value: 258400}
	coordinate:                Coordinate
	adapter:                   Adapter
}

policy: profile.#PolicyAssessment & {
	schema:         "codex-policy-assessment.v0"
	telemetryState: "degraded"
	recommendation: "none"
	reasons:        ["native active context unavailable"]
	projection: {
		projectionID: "policy.v0"
		version:      "0.1.0"
		digest:       "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
	}
	advisoryOnly:          true
	blockNativeCompaction: false
}

write: profile.#DuckDBWriteRequest & {
	schema:    "codex-duckdb-write.v0"
	writer:    "collector"
	operation: "append_normalized"
	runID:     "018f1234-5678-7abc-8def-0123456789ac"
}
