package repobom

#PropertyID: "bom.projection-attribution" |
	"bom.authority-separation" |
	"bom.reference-closure" |
	"bom.path-portability" |
	"bom.stable-identity" |
	"bom.cyclonedx-profile"

#AssertionProperty: {
	id:            #PropertyID
	target:        "#ProducerProjection" | "#RepositoryBOM"
	mutationClass: string
	outcome:       "accept" | "reject"
}

properties: [#PropertyID]: #AssertionProperty
properties: {
	"bom.projection-attribution": {
		id:            "bom.projection-attribution"
		target:        "#ProducerProjection"
		mutationClass: "missing-producer-digest"
		outcome:       "reject"
	}
	"bom.authority-separation": {
		id:            "bom.authority-separation"
		target:        "#ProducerProjection"
		mutationClass: "producer-authority-elevation"
		outcome:       "reject"
	}
	"bom.reference-closure": {
		id:            "bom.reference-closure"
		target:        "#RepositoryBOM"
		mutationClass: "dangling-dependency"
		outcome:       "reject"
	}
	"bom.path-portability": {
		id:            "bom.path-portability"
		target:        "#RepositoryBOM"
		mutationClass: "absolute-realization-path"
		outcome:       "reject"
	}
	"bom.stable-identity": {
		id:            "bom.stable-identity"
		target:        "#RepositoryBOM"
		mutationClass: "duplicate-component-ref"
		outcome:       "reject"
	}
	"bom.cyclonedx-profile": {
		id:            "bom.cyclonedx-profile"
		target:        "#RepositoryBOM"
		mutationClass: "wrong-spec-version"
		outcome:       "reject"
	}
}
