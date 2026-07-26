package negative

import profile "github.com/fatb4f/dotfiles/codexprofile"

Coordinate=coordinate: profile.#SourceCoordinate & {
	source:       {kind: "rollout", sourceID: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", generation: 0}
	sourceOffset: 128
}

invalid: profile.#RawObservationEnvelope & {
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
	}
	retainedPayload: {
		policyID:      "raw.debug"
		redacted:      false
		mediaType:     "application/json"
		content:       "{\"secret\":\"raw\"}"
		contentDigest: "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
	}
	admission: {
		operation:        "append"
		deduplicationKey: Coordinate
	}
}
