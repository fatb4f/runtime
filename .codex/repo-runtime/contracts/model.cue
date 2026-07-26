package repobom

import (
	"list"
	"strings"
)

#Digest: =~"^sha256:[0-9a-f]{64}$"
#ID:     =~"^[a-z][a-z0-9._:/+@-]{0,255}$"
#RelativePath: "." | {
	=~"^[^/\\\\].*$"
	!~"(^|/)(\\.|\\.\\.)(/|$)"
	!~"//"
	!strings.Contains(_, "\\")
}

#RepositoryIdentity: {
	repositoryID: #ID
	locators: [...{
		role: "origin" | "mirror" | "archive"
		uri:  =~"^[a-z][a-z0-9+.-]*://[^[:space:]]+$"
	}]
}

#RepositoryState: {
	repositoryID: #ID
	revision:     =~"^[0-9a-f]{40,64}$"
	tree:         =~"^[0-9a-f]{40,64}$"
	layer:        "committed" | "worktree"
	stateDigest:  #Digest
}

#CheckoutContext: {
	// Operational only: this definition cannot appear in #RepositoryBOM.
	root: string
}

#PartitionBinding: {
	partitionID: "partition.subject.default"
	coordinate: {
		role: "subject"
		name: "default"
	}
	root: "."
}

#ModuleCoordinate: {
	repositoryID:   #ID
	partition:      "subject/default"
	ecosystem:      "python"
	namespace:      =~"^[a-z0-9][a-z0-9._-]*$"
	discriminator?: string
}

#ModuleRealization: {
	coordinate:  #ModuleCoordinate
	surfaceID:   #ID
	partitionID: "partition.subject.default"
	sourcePath:  #RelativePath
	state:       #RepositoryState
}

#EffectiveProfile: {
	profile:     "repository-bom.cyclonedx-1.7.v0"
	digest:      #Digest
	corrections: []
}

#ProducerIdentity: {
	name:    =~"^[a-z][a-z0-9-]+$"
	version: =~"^[0-9]+\\.[0-9]+\\.[0-9]+$"
	digest:  #Digest
}

#ProducerProjection: {
	schema:    "repository-bom.producer-projection.v0"
	producer:  #ProducerIdentity
	authority: "candidate"
	scope: {
		partition: "subject/default"
	}
	inputDigest:      #Digest
	projectionDigest: #Digest
	observations: [...{
		kind:   "repository" | "uv-project" | "uv-lock" | "uv-resolution"
		digest: #Digest
	}] & list.UniqueItems
}

#GenerationIdentity: {
	profileDigest:    #Digest
	producerDigest:   #Digest
	inputDigest:      #Digest
	generationDigest: #Digest
}

#Property: {
	name:  =~"^repo-bom:[a-z][a-z0-9-]*$"
	value: string
}

#Component: {
	type:        "application" | "library"
	"bom-ref":   =~"^urn:repo-bom:[a-z]+:[0-9a-f]{64}$"
	name:        string
	version:     string
	purl?:       =~"^pkg:pypi/[^[:space:]]+$"
	properties?: [...#Property]
}

#Dependency: {
	ref:       =~"^urn:repo-bom:[a-z]+:[0-9a-f]{64}$"
	dependsOn: [...=~"^urn:repo-bom:[a-z]+:[0-9a-f]{64}$"] & list.UniqueItems
}

#RepositoryBOM: {
	bomFormat:    "CycloneDX"
	specVersion:  "1.7"
	serialNumber: =~"^urn:uuid:[0-9a-f-]{36}$"
	version:      1
	metadata: {
		tools: {
			components: [#Component & {
				type: "application"
			}]
		}
		component: #Component & {
			type: "application"
		}
	}
	components: [...#Component & {
		type: "library"
	}]
	dependencies: [...#Dependency]

	_refs: list.Concat([[metadata.component."bom-ref"], [for component in components {
		component."bom-ref"
	}]])
	_refs: list.UniqueItems
	_dependencyRefs: [for dependency in dependencies {
		dependency.ref
	}]
	_dependencyRefs: list.UniqueItems
	_profileValues: [for property in metadata.component.properties if property.name == "repo-bom:profile" {
		property.value
	}]
	_profileValues: ["repository-bom.cyclonedx-1.7.v0"]
	if list.Sort(_refs, list.Ascending) != list.Sort(_dependencyRefs, list.Ascending) {
		_|_
	}
	for dependency in dependencies {
		for target in dependency.dependsOn {
			if !list.Contains(_refs, target) {
				_|_
			}
		}
	}
	for component in list.Concat([[metadata.component], components]) {
		for property in component.properties {
			if property.name == "repo-bom:realization-path" {
				if property.value != "." {
					if property.value !~ "^[^/\\\\].*$" {
						_|_
					}
					if property.value =~ "(^|/)(\\.|\\.\\.)(/|$)|//|\\\\" {
						_|_
					}
				}
			}
			if strings.Contains(strings.ToLower(property.name), "secret") {
				_|_
			}
			if strings.Contains(strings.ToLower(property.name), "raw-environment") {
				_|_
			}
		}
	}
}
