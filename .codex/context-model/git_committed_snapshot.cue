package contextmodel

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"list"
	pathpkg "path"
)

#GitCommittedSnapshotRequest: close({
	schema:       "kernel.git-committed-snapshot-request.v0"
	repositoryID: #GraphID
	path:         #Path | "."
	revision:     #NonEmptyString
})

// Git object identity is transport-neutral. The object format is explicit so
// SHA-1 is not embedded in the repository ontology.
#GitObjectID: close({
	format: #GraphID
	hex:    #NonEmptyString & =~"^[0-9a-f]+$"
})

#GitCommittedKind: "blob" | "tree" | "symlink" | "submodule"

#GitCommittedModeKind: close({
	"040000": "tree"
	"100644": "blob"
	"100664": "blob"
	"100755": "blob"
	"120000": "symlink"
	"160000": "submodule"
})

#GitCommittedOccurrence: close({
	OccurrencePath=path: #Path & !="."
	mode:                #NonEmptyString
	kind:                #GitCommittedKind
	objectID:            #GitObjectID
	size?:               int & >=0

	_pathNormalized: pathpkg.Clean(OccurrencePath) & OccurrencePath
	_modeKnown:      #GitCommittedModeKind[mode]
	_kindCompatible: kind & _modeKnown

})

#GitCommittedSnapshotObservation: close({
	schema: "kernel.git-committed-snapshot-observation.v0"

	repositoryID:      #GraphID
	requestedRevision: #NonEmptyString
	resolvedRevision:  #GitObjectID
	rootTree:          #GitObjectID

	Occurrences=occurrences: [...#GitCommittedOccurrence]

	hydrator: close({
		identity: #GraphID
		digest:   #Digest
	})

	_occurrencePaths: [for occurrence in Occurrences {occurrence.path}]
	_pathsUnique:     list.UniqueItems(_occurrencePaths) & true
	_pathsSorted:     list.IsSortedStrings(_occurrencePaths) & true
})

#GitCommittedSnapshotProjection: close({
	schema: "kernel.git-committed-snapshot-projection.v0"

	Observation=observation:   #GitCommittedSnapshotObservation
	SchemaDigest=schemaDigest: #Digest
	PolicyDigest=policyDigest: #Digest

	_observationJSON:  json.Marshal(Observation)
	observationDigest: "sha256:" + hex.Encode(sha256.Sum256(_observationJSON))

	_moduleID:        "sha256:" + hex.Encode(sha256.Sum256("git-module\u0000" + Observation.repositoryID))
	_rootNamespaceID: "sha256:" + hex.Encode(sha256.Sum256("git-root-namespace\u0000" + Observation.repositoryID))
	_evidenceID:      "sha256:" + hex.Encode(sha256.Sum256("git-observation-evidence\u0000" + observationDigest))
	_snapshotID: "sha256:" + hex.Encode(sha256.Sum256(
		observationDigest + "\u0000" + SchemaDigest + "\u0000" + PolicyDigest + "\u0000" + Observation.hydrator.digest,
	))

	Graph=graph: #ContextGraphSnapshot & {
		snapshotID: _snapshotID

		modules: {
			"\(_moduleID)": {
				kind:            "repository"
				name:            Observation.repositoryID
				rootNamespaceID: _rootNamespaceID
				source: {
					kind:       "git-repository"
					repository: Observation.repositoryID
					revision:   Observation.resolvedRevision.format + ":" + Observation.resolvedRevision.hex
					path:       "."
				}
				properties: {
					rootTree: Observation.rootTree.format + ":" + Observation.rootTree.hex
				}
			}
		}

		namespaces: {
			"\(_rootNamespaceID)": {
				moduleID:          _moduleID
				parentNamespaceID: null
				name:              Observation.repositoryID
				kind:              "repository-root"
				rootPath:          "."
				source: {
					kind:          "git-tree"
					repository:    Observation.repositoryID
					revision:      Observation.resolvedRevision.format + ":" + Observation.resolvedRevision.hex
					path:          "."
					contentDigest: "git-" + Observation.rootTree.format + ":" + Observation.rootTree.hex
				}
			}
		}

		members: {
			for occurrence in Observation.occurrences {
				let occurrenceID = "sha256:" + hex.Encode(sha256.Sum256(
					Observation.repositoryID + "\u0000" + occurrence.path,
				))
				let snapshotOccurrenceID = "sha256:" + hex.Encode(sha256.Sum256(
					Observation.repositoryID + "\u0000" + Observation.resolvedRevision.format + "\u0000" + Observation.resolvedRevision.hex + "\u0000" + occurrence.path,
				))
				"\(occurrenceID)": {
					moduleID:    _moduleID
					namespaceID: _rootNamespaceID
					name:        pathpkg.Base(occurrence.path)
					if occurrence.kind == "tree" {
						kind: "directory"
					}
					if occurrence.kind != "tree" {
						kind: "file"
					}
					path: occurrence.path
					source: {
						kind:          "git-" + occurrence.kind
						repository:    Observation.repositoryID
						revision:      Observation.resolvedRevision.format + ":" + Observation.resolvedRevision.hex
						path:          occurrence.path
						contentDigest: "git-" + occurrence.objectID.format + ":" + occurrence.objectID.hex
					}
					properties: {
						contentIdentity:            "git-object:" + occurrence.objectID.format + ":" + occurrence.objectID.hex
						occurrenceIdentity:         occurrenceID
						snapshotOccurrenceIdentity: snapshotOccurrenceID
						gitMode:                    occurrence.mode
						gitKind:                    occurrence.kind
						if occurrence.size != _|_ {
							gitSizeBytes: occurrence.size
						}
					}
				}
			}
		}

		relationships: {
			let rootRelationshipID = "sha256:" + hex.Encode(sha256.Sum256(
				"contains\u0000" + _moduleID + "\u0000" + _rootNamespaceID,
			))
			"\(rootRelationshipID)": {
				subject:     {kind: "module", id: _moduleID}
				predicate:   "contains"
				object:      {kind: "namespace", id: _rootNamespaceID}
				evidenceIDs: [_evidenceID]
			}

			for occurrence in Observation.occurrences if pathpkg.Dir(occurrence.path) == "." {
				let occurrenceID = "sha256:" + hex.Encode(sha256.Sum256(
					Observation.repositoryID + "\u0000" + occurrence.path,
				))
				let relationshipID = "sha256:" + hex.Encode(sha256.Sum256(
					"contains\u0000" + _rootNamespaceID + "\u0000" + occurrenceID,
				))
				"\(relationshipID)": {
					subject:     {kind: "namespace", id: _rootNamespaceID}
					predicate:   "contains"
					object:      {kind: "member", id: occurrenceID}
					evidenceIDs: [_evidenceID]
				}
			}

			for occurrence in Observation.occurrences if pathpkg.Dir(occurrence.path) != "." {
				let parentPath = pathpkg.Dir(occurrence.path)
				let parentID = "sha256:" + hex.Encode(sha256.Sum256(
					Observation.repositoryID + "\u0000" + parentPath,
				))
				let occurrenceID = "sha256:" + hex.Encode(sha256.Sum256(
					Observation.repositoryID + "\u0000" + occurrence.path,
				))
				let relationshipID = "sha256:" + hex.Encode(sha256.Sum256(
					"contains\u0000" + parentID + "\u0000" + occurrenceID,
				))
				"\(relationshipID)": {
					subject:     {kind: "member", id: parentID}
					predicate:   "contains"
					object:      {kind: "member", id: occurrenceID}
					evidenceIDs: [_evidenceID]
				}
			}
		}

		evidence: {
			"\(_evidenceID)": {
				kind:     "observation"
				subject:  {kind: "module", id: _moduleID}
				producer: null
				source: {
					kind:          "git-committed-snapshot"
					repository:    Observation.repositoryID
					revision:      Observation.resolvedRevision.format + ":" + Observation.resolvedRevision.hex
					path:          "."
					contentDigest: observationDigest
				}
				authority:     "candidate"
				payloadDigest: observationDigest
				diagnostics:   []
				properties: {
					requestedRevision: Observation.requestedRevision
					resolvedRevision:  Observation.resolvedRevision.format + ":" + Observation.resolvedRevision.hex
					rootTree:          Observation.rootTree.format + ":" + Observation.rootTree.hex
					hydratorIdentity:  Observation.hydrator.identity
					hydratorDigest:    Observation.hydrator.digest
				}
			}
		}

		provenance: {
			authorityDigest: PolicyDigest
			schemaDigest:    SchemaDigest
			hydratorDigest:  Observation.hydrator.digest
			baseRevision:    Observation.resolvedRevision.format + ":" + Observation.resolvedRevision.hex
			baseTree:        Observation.rootTree.format + ":" + Observation.rootTree.hex
		}
	}

	collected: #ContextCollectedEvidenceEnvelope & {
		state: {
			evidenceID:         _evidenceID
			snapshotID:         Graph.snapshotID
			evidence:           Graph.evidence[_evidenceID]
			effectiveAuthority: "candidate"
		}
	}
})

#GitCommittedSnapshotPropertyID:
	"determinism" |
		"rename-content-preserved" |
		"content-edit-content-changed" |
		"unrelated-entry-preserved" |
		"mode-change-content-preserved" |
		"symlink-not-traversed" |
		"submodule-not-traversed" |
		"revision-bound" |
		"unknown-field-rejected" |
		"duplicate-path-rejected" |
		"unsorted-path-rejected" |
		"incompatible-mode-rejected" |
		"non-normalized-path-rejected" |
		"noncanonical-revision-rejected" |
		"malformed-object-id-rejected" |
		"malformed-digest-rejected" |
		"opaque-symlink-descendant-rejected" |
		"opaque-submodule-descendant-rejected" |
		"elevated-authority-rejected"

// This manifest is consumed by the Go/CUE qualification runner. Its concrete
// key set is the declared side of the declared=generated=executed=reported gate.
gitCommittedSnapshotProperties: close({
	"determinism":                          true
	"rename-content-preserved":             true
	"content-edit-content-changed":         true
	"unrelated-entry-preserved":            true
	"mode-change-content-preserved":        true
	"symlink-not-traversed":                true
	"submodule-not-traversed":              true
	"revision-bound":                       true
	"unknown-field-rejected":               true
	"duplicate-path-rejected":              true
	"unsorted-path-rejected":               true
	"incompatible-mode-rejected":           true
	"non-normalized-path-rejected":         true
	"noncanonical-revision-rejected":       true
	"malformed-object-id-rejected":         true
	"malformed-digest-rejected":            true
	"opaque-symlink-descendant-rejected":   true
	"opaque-submodule-descendant-rejected": true
	"elevated-authority-rejected":          true
})

#GitCommittedSnapshotMutationKind:
	"environment-perturbation" |
		"rename-only" |
		"content-edit" |
		"unrelated-entry-addition" |
		"mode-only-change" |
		"symlink-traversal-attempt" |
		"submodule-traversal-attempt" |
		"selector-target-move" |
		"unknown-field-insertion" |
		"duplicate-path-insertion" |
		"path-order-perturbation" |
		"mode-kind-incompatibility" |
		"path-normalization-escape" |
		"symbolic-revision-insertion" |
		"object-id-corruption" |
		"digest-corruption" |
		"symlink-descendant-insertion" |
		"submodule-descendant-insertion" |
		"authority-elevation-without-admission"

#GitCommittedSnapshotInvariantTerm:
	"normalized-observation-bytes" |
		"content-identity" |
		"occurrence-identity" |
		"snapshot-occurrence-identity" |
		"occurrence-metadata" |
		"opaque-entry" |
		"resolved-revision" |
		"closed-structure" |
		"unique-paths" |
		"canonical-order" |
		"mode-kind-compatibility" |
		"normalized-path" |
		"canonical-revision" |
		"object-identity" |
		"hydrator-provenance" |
		"collection-authority"

#GitCommittedSnapshotStrategyCoverage: close({
	positive:    [#GraphID, ...#GraphID]
	negative:    [#GraphID, ...#GraphID]
	boundary:    [#GraphID, ...#GraphID]
	metamorphic: [#GraphID, ...#GraphID]
	environment: [#GraphID, ...#GraphID]
})

#GitCommittedSnapshotProperty: close({
	id:            #GitCommittedSnapshotPropertyID
	description:   #NonEmptyString
	mutation:      #GitCommittedSnapshotMutationKind
	preconditions: [...#GraphID]
	preserves:     [...#GitCommittedSnapshotInvariantTerm]
	changes:       [...#GitCommittedSnapshotInvariantTerm]
	expected:      "accept" | "reject"
	strategies:    #GitCommittedSnapshotStrategyCoverage
})

#GitCommittedSnapshotPropertyCatalog: close({
	schema: "kernel.git-committed-snapshot-properties.v0"
	properties: [ID=#GitCommittedSnapshotPropertyID]: #GitCommittedSnapshotProperty & {
		id: ID
		strategies: {
			positive:    ["schema-derived-valid"]
			negative:    ["invariant-targeted-invalid"]
			boundary:    ["lower-and-upper-bounds"]
			metamorphic: ["property-" + ID]
			environment: ["controlled-process-environment"]
		}
	}
})

gitCommittedSnapshotPropertyCatalog: #GitCommittedSnapshotPropertyCatalog & {
	properties: {
		"determinism": {
			description:   "Controlled environment perturbations preserve byte-identical normalized observations for the same request and resolved commit."
			mutation:      "environment-perturbation"
			preconditions: ["same-repository", "same-request", "same-resolved-revision", "same-hydrator-identity"]
			preserves:     ["normalized-observation-bytes"]
			changes:       []
			expected:      "accept"
		}
		"rename-content-preserved": {
			description:   "A rename-only mutation preserves Git object content identity while changing stable and snapshot occurrence identities."
			mutation:      "rename-only"
			preconditions: ["same-repository", "same-object-id", "different-normalized-path", "different-resolved-revision"]
			preserves:     ["content-identity"]
			changes:       ["occurrence-identity", "snapshot-occurrence-identity"]
			expected:      "accept"
		}
		"content-edit-content-changed": {
			description:   "A content edit at one path changes content and snapshot occurrence identity while preserving stable occurrence identity."
			mutation:      "content-edit"
			preconditions: ["same-repository", "same-normalized-path", "different-object-id", "different-resolved-revision"]
			preserves:     ["occurrence-identity"]
			changes:       ["content-identity", "snapshot-occurrence-identity"]
			expected:      "accept"
		}
		"unrelated-entry-preserved": {
			description:   "Adding an unrelated entry preserves content and stable occurrence identity for every unaffected path."
			mutation:      "unrelated-entry-addition"
			preconditions: ["same-repository", "same-unaffected-path", "same-unaffected-object-id", "different-resolved-revision"]
			preserves:     ["content-identity", "occurrence-identity"]
			changes:       ["snapshot-occurrence-identity"]
			expected:      "accept"
		}
		"mode-change-content-preserved": {
			description:   "A mode-only change preserves content and stable occurrence identity while changing occurrence metadata and snapshot occurrence identity."
			mutation:      "mode-only-change"
			preconditions: ["same-repository", "same-normalized-path", "same-object-id", "different-mode", "different-resolved-revision"]
			preserves:     ["content-identity", "occurrence-identity"]
			changes:       ["occurrence-metadata", "snapshot-occurrence-identity"]
			expected:      "accept"
		}
		"symlink-not-traversed": {
			description:   "A symlink remains one opaque committed occurrence and is never traversed."
			mutation:      "symlink-traversal-attempt"
			preconditions: ["symlink-mode-kind-compatible"]
			preserves:     ["opaque-entry"]
			changes:       []
			expected:      "accept"
		}
		"submodule-not-traversed": {
			description:   "A gitlink remains one opaque committed occurrence and is never traversed."
			mutation:      "submodule-traversal-attempt"
			preconditions: ["submodule-mode-kind-compatible"]
			preserves:     ["opaque-entry"]
			changes:       []
			expected:      "accept"
		}
		"revision-bound": {
			description:   "Hydration binds an exact resolved commit so a later selector target move cannot change the bound observation."
			mutation:      "selector-target-move"
			preconditions: ["selector-resolves-to-commit", "exact-commit-request"]
			preserves:     ["resolved-revision", "normalized-observation-bytes"]
			changes:       []
			expected:      "accept"
		}
		"unknown-field-rejected": {
			description:   "Closed observation and projection boundaries reject unknown fields."
			mutation:      "unknown-field-insertion"
			preconditions: ["valid-closed-document"]
			preserves:     ["closed-structure"]
			changes:       []
			expected:      "reject"
		}
		"duplicate-path-rejected": {
			description:   "Two committed occurrences cannot claim the same normalized path."
			mutation:      "duplicate-path-insertion"
			preconditions: ["valid-observation", "existing-path"]
			preserves:     ["unique-paths"]
			changes:       []
			expected:      "reject"
		}
		"unsorted-path-rejected": {
			description:   "Committed occurrences must remain in canonical path order."
			mutation:      "path-order-perturbation"
			preconditions: ["valid-observation", "multiple-paths"]
			preserves:     ["canonical-order"]
			changes:       []
			expected:      "reject"
		}
		"incompatible-mode-rejected": {
			description:   "A Git occurrence mode must agree with its declared kind."
			mutation:      "mode-kind-incompatibility"
			preconditions: ["valid-observation", "known-git-mode"]
			preserves:     ["mode-kind-compatibility"]
			changes:       []
			expected:      "reject"
		}
		"non-normalized-path-rejected": {
			description:   "Occurrence paths reject absolute, escaping, and non-normalized forms."
			mutation:      "path-normalization-escape"
			preconditions: ["valid-observation", "existing-path"]
			preserves:     ["normalized-path"]
			changes:       []
			expected:      "reject"
		}
		"noncanonical-revision-rejected": {
			description:   "Normalized observations bind requestedRevision to the exact resolved commit hex."
			mutation:      "symbolic-revision-insertion"
			preconditions: ["valid-observation", "resolved-commit"]
			preserves:     ["canonical-revision", "resolved-revision"]
			changes:       []
			expected:      "reject"
		}
		"malformed-object-id-rejected": {
			description:   "Git object identifiers reject empty, uppercase, short, and non-hex encodings."
			mutation:      "object-id-corruption"
			preconditions: ["valid-observation", "existing-object-id"]
			preserves:     ["object-identity"]
			changes:       []
			expected:      "reject"
		}
		"malformed-digest-rejected": {
			description:   "Hydrator provenance requires a canonical sha256 digest."
			mutation:      "digest-corruption"
			preconditions: ["valid-observation", "bound-hydrator"]
			preserves:     ["hydrator-provenance"]
			changes:       []
			expected:      "reject"
		}
		"opaque-symlink-descendant-rejected": {
			description:   "A symlink is opaque and cannot contain another committed occurrence."
			mutation:      "symlink-descendant-insertion"
			preconditions: ["valid-observation", "symlink-occurrence"]
			preserves:     ["opaque-entry"]
			changes:       []
			expected:      "reject"
		}
		"opaque-submodule-descendant-rejected": {
			description:   "A submodule is opaque and cannot contain another committed occurrence."
			mutation:      "submodule-descendant-insertion"
			preconditions: ["valid-observation", "submodule-occurrence"]
			preserves:     ["opaque-entry"]
			changes:       []
			expected:      "reject"
		}
		"elevated-authority-rejected": {
			description:   "Collection cannot elevate evidence beyond candidate authority without admission."
			mutation:      "authority-elevation-without-admission"
			preconditions: ["valid-projection", "no-admission-record"]
			preserves:     ["collection-authority"]
			changes:       []
			expected:      "reject"
		}
	}
}

// Both directions are evaluated by CUE so the simple declaration manifest used
// by the Go equality gate cannot drift from the assertion-bearing catalog.
_gitCommittedSnapshotCatalogCoversManifest: {
	for ID, _ in gitCommittedSnapshotProperties {
		"\(ID)": gitCommittedSnapshotPropertyCatalog.properties[ID]
	}
}
_gitCommittedSnapshotManifestCoversCatalog: {
	for ID, _ in gitCommittedSnapshotPropertyCatalog.properties {
		"\(ID)": gitCommittedSnapshotProperties[ID]
	}
}
