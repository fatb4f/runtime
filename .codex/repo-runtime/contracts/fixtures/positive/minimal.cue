package positive

import bom "github.com/fatb4f/repository-bom/contracts@v0:repobom"

projection: bom.#ProducerProjection & {
	schema: "repository-bom.producer-projection.v0"
	producer: {
		name:    "repository-bom-runtime"
		version: "0.1.0"
		digest:  "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	}
	authority: "candidate"
	scope: partition: "subject/default"
	inputDigest:      "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
	projectionDigest: "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
	observations: [{
		kind:   "uv-lock"
		digest: "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
	}]
}

bomDocument: bom.#RepositoryBOM & {
	bomFormat:    "CycloneDX"
	specVersion:  "1.7"
	serialNumber: "urn:uuid:11111111-1111-1111-1111-111111111111"
	version:      1
	metadata: {
		tools: components: [{
			type:      "application"
			"bom-ref": "urn:repo-bom:tool:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
			name:      "repository-bom-runtime"
			version:   "0.1.0"
		}]
		component: {
			type:       "application"
			"bom-ref":  "urn:repo-bom:repository:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
			name:       "repository:example"
			version:    "1111111111111111111111111111111111111111"
			properties: [{name: "repo-bom:profile", value: "repository-bom.cyclonedx-1.7.v0"}]
		}
	}
	components: [{
		type:       "library"
		"bom-ref":  "urn:repo-bom:module:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
		name:       "example"
		version:    "1.0.0"
		purl:       "pkg:pypi/example@1.0.0"
		properties: [{name: "repo-bom:realization-path", value: "."}]
	}]
	dependencies: [{
		ref:       "urn:repo-bom:repository:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
		dependsOn: ["urn:repo-bom:module:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"]
	}, {
		ref:       "urn:repo-bom:module:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
		dependsOn: []
	}]
}
