package authority

import bom "github.com/fatb4f/repository-bom/contracts@v0:repobom"

invalid: bom.#ProducerProjection & {
	schema: "repository-bom.producer-projection.v0"
	producer: {
		name:    "repository-bom-runtime"
		version: "0.1.0"
		digest:  "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	}
	authority: "admitted"
	scope: partition: "subject/default"
	inputDigest:      "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
	projectionDigest: "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
	observations:     []
}
