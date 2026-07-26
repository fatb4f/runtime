package contextmodel

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"list"
	"strings"
)

// Resolution normalizes every branch, tag, symbolic, or exact-hash selector to
// the exact commit hex. Raw selector spelling remains request transport only.
#GitCommittedSnapshotObservation: {
	ResolvedRevision=resolvedRevision: #GitObjectID
	requestedRevision:                 ResolvedRevision.hex

	Occurrences=occurrences: [...#GitCommittedOccurrence]

	// Symlinks and gitlinks are opaque structural occurrences. No emitted path
	// may claim to be a descendant of either entry.
	_opaqueDescendants: [
		for opaque in Occurrences if opaque.kind == "symlink" || opaque.kind == "submodule" {
			for candidate in Occurrences if strings.HasPrefix(candidate.path, opaque.path + "/") {
				_|_("opaque Git occurrence has descendant: " + candidate.path)
			}
		}
	]
}

#GitCommittedSnapshotFuzzPropertyID: #GitCommittedSnapshotPropertyID & (
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
		"elevated-authority-rejected")

gitCommittedSnapshotFuzzProperties: close({
	"unknown-field-rejected":               gitCommittedSnapshotPropertyCatalog.properties["unknown-field-rejected"]
	"duplicate-path-rejected":              gitCommittedSnapshotPropertyCatalog.properties["duplicate-path-rejected"]
	"unsorted-path-rejected":               gitCommittedSnapshotPropertyCatalog.properties["unsorted-path-rejected"]
	"incompatible-mode-rejected":           gitCommittedSnapshotPropertyCatalog.properties["incompatible-mode-rejected"]
	"non-normalized-path-rejected":         gitCommittedSnapshotPropertyCatalog.properties["non-normalized-path-rejected"]
	"noncanonical-revision-rejected":       gitCommittedSnapshotPropertyCatalog.properties["noncanonical-revision-rejected"]
	"malformed-object-id-rejected":         gitCommittedSnapshotPropertyCatalog.properties["malformed-object-id-rejected"]
	"malformed-digest-rejected":            gitCommittedSnapshotPropertyCatalog.properties["malformed-digest-rejected"]
	"opaque-symlink-descendant-rejected":   gitCommittedSnapshotPropertyCatalog.properties["opaque-symlink-descendant-rejected"]
	"opaque-submodule-descendant-rejected": gitCommittedSnapshotPropertyCatalog.properties["opaque-submodule-descendant-rejected"]
	"elevated-authority-rejected":          gitCommittedSnapshotPropertyCatalog.properties["elevated-authority-rejected"]
})

#GitCommittedSnapshotCandidateFixture: close({
	documentJSON:   #NonEmptyString
	documentDigest: #Digest
	_digestMatch:   documentDigest & ("sha256:" + hex.Encode(sha256.Sum256(documentJSON)))
})

#GitCommittedSnapshotAssertionCandidate: close({
	schema:                 "kernel.git-committed-snapshot-assertion-candidate.v1"
	proposedPropertyID:     #GraphID
	targetSchemaDefinition: "#GitCommittedSnapshotObservation" | "#GitCommittedSnapshotProjection"
	mutationClass:          #GitCommittedSnapshotMutationKind
	documentKind:           "observation" | "projection"
	toolIdentities: [close({
		name:    #GraphID
		version: #NonEmptyString
	}), ...close({
		name:    #GraphID
		version: #NonEmptyString
	})]
	originalFixture:        #GitCommittedSnapshotCandidateFixture
	minimizedFixture:       #GitCommittedSnapshotCandidateFixture
	preservedTerms:         [...#GitCommittedSnapshotInvariantTerm]
	changedTerms:           [...#GitCommittedSnapshotInvariantTerm]
	affectedOracleSurfaces: ["cue-validation" | "typed-validation" | "hydrator-execution" | "normalized-serialization", ...("cue-validation" | "typed-validation" | "hydrator-execution" | "normalized-serialization")]
	expected:               "reject"
	observed:               "accept"
})

#GitCommittedSnapshotRegressionQueue: close({
	schema:    "kernel.git-committed-snapshot-regression-queue.v0"
	authority: "none"
	review: close({
		status:     "pending"
		reviewedBy: null
		promotion:  null
	})
	candidates: [#GitCommittedSnapshotAssertionCandidate, ...#GitCommittedSnapshotAssertionCandidate]
})

#GitCommittedSnapshotQualificationReport: close({
	schema:           "kernel.git-committed-snapshot-qualification-report.v1"
	resolvedRevision: #NonEmptyString & =~"^[0-9a-f]+$"
	hydratorDigest:   #Digest
	fixtureCommits: close({
		A: #NonEmptyString & =~"^[0-9a-f]+$"
		B: #NonEmptyString & =~"^[0-9a-f]+$"
		C: #NonEmptyString & =~"^[0-9a-f]+$"
		D: #NonEmptyString & =~"^[0-9a-f]+$"
		E: #NonEmptyString & =~"^[0-9a-f]+$"
		F: #NonEmptyString & =~"^[0-9a-f]+$"
	})

	Declared=declaredPropertyIDs: [...#GitCommittedSnapshotPropertyID]
	generatedPropertyIDs:         Declared
	executedPropertyIDs:          Declared
	reportedPropertyIDs:          Declared

	propertyReport: close({
		schema: "kernel.git-committed-snapshot-property-report.v0"
		results: [...close({
			propertyID: #GitCommittedSnapshotPropertyID
			status:     "passed"
		})]
		_resultIDs: [for result in results {result.propertyID}]
		_unique:    list.UniqueItems(_resultIDs) & true
	})

	// The report itself remains canonical JSON-compatible and closed.
	_reportJSON: json.Marshal({
		schema:               schema
		resolvedRevision:     resolvedRevision
		hydratorDigest:       hydratorDigest
		fixtureCommits:       fixtureCommits
		declaredPropertyIDs:  declaredPropertyIDs
		generatedPropertyIDs: generatedPropertyIDs
		executedPropertyIDs:  executedPropertyIDs
		reportedPropertyIDs:  reportedPropertyIDs
		propertyReport:       propertyReport
	})
})
