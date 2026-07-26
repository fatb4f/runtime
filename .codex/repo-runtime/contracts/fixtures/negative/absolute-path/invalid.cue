package absolutepath

import bom "github.com/fatb4f/repository-bom/contracts@v0:repobom"

invalid: bom.#RepositoryBOM & {
	bomFormat:    "CycloneDX"
	specVersion:  "1.7"
	serialNumber: "urn:uuid:11111111-1111-1111-1111-111111111111"
	version:      1
	metadata: {
		tools: components: [{
			type:      "application"
			"bom-ref": "urn:repo-bom:tool:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
			name:      "tool"
			version:   "1.0.0"
		}]
		component: {
			type:      "application"
			"bom-ref": "urn:repo-bom:repository:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
			name:      "repository:example"
			version:   "1111111111111111111111111111111111111111"
		}
	}
	components: [{
		type:       "library"
		"bom-ref":  "urn:repo-bom:module:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
		name:       "example"
		version:    "1.0.0"
		properties: [{name: "repo-bom:realization-path", value: "/private/example"}]
	}]
	dependencies: [{
		ref:       "urn:repo-bom:repository:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
		dependsOn: ["urn:repo-bom:module:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"]
	}, {
		ref:       "urn:repo-bom:module:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
		dependsOn: []
	}]
}
