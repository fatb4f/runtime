package contextmodel

import (
	"encoding/json"
	"list"
	"strings"
)

// Opaque entries can occur in either overlay, but no layer may claim a path
// beneath a symlink or gitlink that the collector was forbidden to traverse.
#GitIndexOverlay: {
	Occurrences=occurrences: [...#GitIndexOverlayOccurrence]
	_opaqueDescendants: [
		for opaque in Occurrences if opaque.status != "deleted" {
			if opaque.kind == "symlink" || opaque.kind == "submodule" {
				for candidate in Occurrences if strings.HasPrefix(candidate.path, opaque.path + "/") {
					_|_("opaque index occurrence has descendant: " + candidate.path)
				}
			}
		}
	]
}

#GitWorktreeOverlay: {
	Occurrences=occurrences: [...#GitWorktreeOverlayOccurrence]
	_opaqueDescendants: [
		for opaque in Occurrences if opaque.status != "deleted" {
			if opaque.kind == "symlink" || opaque.kind == "submodule" {
				for candidate in Occurrences if strings.HasPrefix(candidate.path, opaque.path + "/") {
					_|_("opaque worktree occurrence has descendant: " + candidate.path)
				}
			}
		}
	]
}

#GitOverlayPropertyID:
	"overlay-determinism" |
		"clean-overlay-preserves-base" |
		"exact-base-bound" |
		"index-worktree-distinct" |
		"same-path-layers-coexist" |
		"untracked-not-staged" |
		"staged-addition-observed" |
		"staged-modification-observed" |
		"staged-deletion-explicit" |
		"unstaged-modification-observed" |
		"unstaged-deletion-explicit" |
		"executable-mode-change-observed" |
		"symlink-not-followed" |
		"submodule-not-traversed" |
		"deletion-content-absent" |
		"unrelated-change-identity-preserved" |
		"unknown-field-rejected" |
		"duplicate-index-path-rejected" |
		"duplicate-worktree-path-rejected" |
		"unsorted-layer-path-rejected" |
		"invalid-mode-kind-rejected" |
		"non-normalized-path-rejected" |
		"broken-base-binding-rejected" |
		"elevated-authority-rejected"

// This concrete key manifest is the declaration side of the four-way property
// equality gate. Generated fixture cases, Go runners, and persisted reports are
// maintained and compared independently.
gitOverlayProperties: close({
	"overlay-determinism":                 true
	"clean-overlay-preserves-base":        true
	"exact-base-bound":                    true
	"index-worktree-distinct":             true
	"same-path-layers-coexist":            true
	"untracked-not-staged":                true
	"staged-addition-observed":            true
	"staged-modification-observed":        true
	"staged-deletion-explicit":            true
	"unstaged-modification-observed":      true
	"unstaged-deletion-explicit":          true
	"executable-mode-change-observed":     true
	"symlink-not-followed":                true
	"submodule-not-traversed":             true
	"deletion-content-absent":             true
	"unrelated-change-identity-preserved": true
	"unknown-field-rejected":              true
	"duplicate-index-path-rejected":       true
	"duplicate-worktree-path-rejected":    true
	"unsorted-layer-path-rejected":        true
	"invalid-mode-kind-rejected":          true
	"non-normalized-path-rejected":        true
	"broken-base-binding-rejected":        true
	"elevated-authority-rejected":         true
})

#GitOverlayMutationKind:
	"environment-and-enumeration-perturbation" |
		"empty-overlay" |
		"base-revision-substitution" |
		"layer-collapse" |
		"same-path-dual-change" |
		"untracked-index-insertion" |
		"staged-addition" |
		"staged-modification" |
		"staged-deletion" |
		"unstaged-modification" |
		"unstaged-deletion" |
		"executable-mode-change" |
		"symlink-traversal-attempt" |
		"submodule-traversal-attempt" |
		"deletion-content-insertion" |
		"unrelated-path-change" |
		"unknown-field-insertion" |
		"duplicate-index-path-insertion" |
		"duplicate-worktree-path-insertion" |
		"path-order-perturbation" |
		"mode-kind-incompatibility" |
		"path-normalization-escape" |
		"projection-base-substitution" |
		"authority-elevation-without-admission"

#GitOverlayInvariantTerm:
	"normalized-observation-bytes" |
		"committed-graph" |
		"base-revision" |
		"index-layer" |
		"worktree-layer" |
		"path-occurrence-identity" |
		"layer-occurrence-identity" |
		"content-identity" |
		"deletion-occurrence" |
		"mode-metadata" |
		"opaque-entry" |
		"closed-structure" |
		"unique-layer-paths" |
		"canonical-layer-order" |
		"mode-kind-compatibility" |
		"normalized-path" |
		"collection-authority"

#GitOverlayStrategyCoverage: close({
	positive:    [#GraphID, ...#GraphID]
	negative:    [#GraphID, ...#GraphID]
	boundary:    [#GraphID, ...#GraphID]
	metamorphic: [#GraphID, ...#GraphID]
	environment: [#GraphID, ...#GraphID]
})

#GitOverlayProperty: close({
	id:            #GitOverlayPropertyID
	description:   #NonEmptyString
	mutation:      #GitOverlayMutationKind
	preconditions: [...#GraphID]
	preserves:     [...#GitOverlayInvariantTerm]
	changes:       [...#GitOverlayInvariantTerm]
	expected:      "accept" | "reject"
	strategies:    #GitOverlayStrategyCoverage
})

#GitOverlayPropertyCatalog: close({
	schema: "kernel.git-overlay-properties.v0"
	properties: [ID=#GitOverlayPropertyID]: #GitOverlayProperty & {
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

gitOverlayPropertyCatalog: #GitOverlayPropertyCatalog & {
	properties: {
		"overlay-determinism": {
			description:   "The same repository state, exact base, and hydrator identity produce byte-identical canonical output."
			mutation:      "environment-and-enumeration-perturbation"
			preconditions: ["same-repository-state", "same-exact-base", "same-hydrator-identity"]
			preserves:     ["normalized-observation-bytes"]
			changes:       []
			expected:      "accept"
		}
		"clean-overlay-preserves-base": {
			description:   "Empty index and worktree overlays project the committed graph without any graph mutation."
			mutation:      "empty-overlay"
			preconditions: ["clean-index", "clean-worktree", "valid-committed-projection"]
			preserves:     ["committed-graph"]
			changes:       []
			expected:      "accept"
		}
		"exact-base-bound": {
			description:   "Collection resolves and verifies the exact requested base commit before reading either mutable layer."
			mutation:      "base-revision-substitution"
			preconditions: ["valid-overlay-request", "head-resolves-to-commit"]
			preserves:     ["base-revision"]
			changes:       []
			expected:      "reject"
		}
		"index-worktree-distinct": {
			description:   "Staged index facts never collapse into unstaged worktree facts."
			mutation:      "layer-collapse"
			preconditions: ["staged-change", "unstaged-change"]
			preserves:     ["index-layer", "worktree-layer", "layer-occurrence-identity"]
			changes:       []
			expected:      "reject"
		}
		"same-path-layers-coexist": {
			description:   "Index and worktree changes for one path coexist as two layer occurrences with one stable path occurrence identity."
			mutation:      "same-path-dual-change"
			preconditions: ["path-changed-in-index", "same-path-changed-in-worktree"]
			preserves:     ["path-occurrence-identity", "index-layer", "worktree-layer"]
			changes:       ["layer-occurrence-identity", "content-identity"]
			expected:      "accept"
		}
		"untracked-not-staged": {
			description:   "A worktree path absent from the index is untracked and cannot appear in the index layer."
			mutation:      "untracked-index-insertion"
			preconditions: ["path-absent-from-index", "path-present-in-worktree"]
			preserves:     ["index-layer", "worktree-layer"]
			changes:       []
			expected:      "reject"
		}
		"staged-addition-observed": {
			description:   "An index path absent from the committed base is emitted as an added index occurrence."
			mutation:      "staged-addition"
			preconditions: ["path-absent-from-base", "path-present-in-index"]
			preserves:     ["index-layer", "content-identity"]
			changes:       ["layer-occurrence-identity"]
			expected:      "accept"
		}
		"staged-modification-observed": {
			description:   "An index object differing from the committed base is emitted as a modified index occurrence."
			mutation:      "staged-modification"
			preconditions: ["path-present-in-base", "path-present-in-index", "object-or-mode-differs"]
			preserves:     ["path-occurrence-identity", "index-layer"]
			changes:       ["content-identity"]
			expected:      "accept"
		}
		"staged-deletion-explicit": {
			description:   "A committed path absent from the index is emitted as an explicit deletion without fabricated content identity."
			mutation:      "staged-deletion"
			preconditions: ["path-present-in-base", "path-absent-from-index"]
			preserves:     ["path-occurrence-identity", "deletion-occurrence"]
			changes:       []
			expected:      "accept"
		}
		"unstaged-modification-observed": {
			description:   "A worktree object differing from the index is emitted as a modified worktree occurrence."
			mutation:      "unstaged-modification"
			preconditions: ["path-present-in-index", "path-present-in-worktree", "object-or-mode-differs"]
			preserves:     ["path-occurrence-identity", "worktree-layer"]
			changes:       ["content-identity"]
			expected:      "accept"
		}
		"unstaged-deletion-explicit": {
			description:   "An index path absent from the worktree is emitted as an explicit worktree deletion."
			mutation:      "unstaged-deletion"
			preconditions: ["path-present-in-index", "path-absent-from-worktree"]
			preserves:     ["path-occurrence-identity", "deletion-occurrence"]
			changes:       []
			expected:      "accept"
		}
		"executable-mode-change-observed": {
			description:   "Executable-bit changes are emitted with modeChanged while preserving blob content identity."
			mutation:      "executable-mode-change"
			preconditions: ["same-file-bytes", "executable-bit-differs"]
			preserves:     ["content-identity", "path-occurrence-identity"]
			changes:       ["mode-metadata"]
			expected:      "accept"
		}
		"symlink-not-followed": {
			description:   "Symlinks are hashed from link text and never followed or traversed."
			mutation:      "symlink-traversal-attempt"
			preconditions: ["symlink-present-in-overlay"]
			preserves:     ["opaque-entry", "content-identity"]
			changes:       []
			expected:      "accept"
		}
		"submodule-not-traversed": {
			description:   "Gitlinks remain opaque submodule-shaped occurrences and are never traversed."
			mutation:      "submodule-traversal-attempt"
			preconditions: ["gitlink-present-in-overlay"]
			preserves:     ["opaque-entry", "content-identity"]
			changes:       []
			expected:      "accept"
		}
		"deletion-content-absent": {
			description:   "Deleted occurrences reject object, mode, kind, size, and content identity fields."
			mutation:      "deletion-content-insertion"
			preconditions: ["valid-deletion-occurrence"]
			preserves:     ["deletion-occurrence", "closed-structure"]
			changes:       []
			expected:      "reject"
		}
		"unrelated-change-identity-preserved": {
			description:   "Adding an unrelated overlay path preserves unaffected content, path occurrence, and layer identities."
			mutation:      "unrelated-path-change"
			preconditions: ["existing-unaffected-overlay-path", "new-distinct-path"]
			preserves:     ["content-identity", "path-occurrence-identity", "layer-occurrence-identity"]
			changes:       []
			expected:      "accept"
		}
		"unknown-field-rejected": {
			description:   "Closed request, layer, occurrence, observation, and projection boundaries reject unknown fields."
			mutation:      "unknown-field-insertion"
			preconditions: ["valid-closed-document"]
			preserves:     ["closed-structure"]
			changes:       []
			expected:      "reject"
		}
		"duplicate-index-path-rejected": {
			description:   "The index layer rejects duplicate normalized paths."
			mutation:      "duplicate-index-path-insertion"
			preconditions: ["valid-index-overlay", "existing-index-path"]
			preserves:     ["unique-layer-paths"]
			changes:       []
			expected:      "reject"
		}
		"duplicate-worktree-path-rejected": {
			description:   "The worktree layer rejects duplicate normalized paths."
			mutation:      "duplicate-worktree-path-insertion"
			preconditions: ["valid-worktree-overlay", "existing-worktree-path"]
			preserves:     ["unique-layer-paths"]
			changes:       []
			expected:      "reject"
		}
		"unsorted-layer-path-rejected": {
			description:   "Both overlay layers require canonical bytewise path ordering."
			mutation:      "path-order-perturbation"
			preconditions: ["valid-overlay", "multiple-layer-paths"]
			preserves:     ["canonical-layer-order"]
			changes:       []
			expected:      "reject"
		}
		"invalid-mode-kind-rejected": {
			description:   "Present overlay occurrences reject unknown modes and incompatible mode-kind pairs."
			mutation:      "mode-kind-incompatibility"
			preconditions: ["valid-present-occurrence"]
			preserves:     ["mode-kind-compatibility"]
			changes:       []
			expected:      "reject"
		}
		"non-normalized-path-rejected": {
			description:   "Overlay paths are non-empty, normalized, and repository-relative."
			mutation:      "path-normalization-escape"
			preconditions: ["valid-overlay-occurrence"]
			preserves:     ["normalized-path"]
			changes:       []
			expected:      "reject"
		}
		"broken-base-binding-rejected": {
			description:   "Projection rejects any repository, revision, tree, schema, or policy mismatch with the committed base."
			mutation:      "projection-base-substitution"
			preconditions: ["valid-committed-projection", "valid-overlay-observation"]
			preserves:     ["committed-graph", "base-revision"]
			changes:       []
			expected:      "reject"
		}
		"elevated-authority-rejected": {
			description:   "Overlay hydration, projection, and serialization cannot elevate collected evidence beyond candidate authority."
			mutation:      "authority-elevation-without-admission"
			preconditions: ["valid-overlay-projection", "no-admission-record"]
			preserves:     ["collection-authority"]
			changes:       []
			expected:      "reject"
		}
	}
}

_gitOverlayCatalogCoversManifest: {
	for ID, _ in gitOverlayProperties {
		"\(ID)": gitOverlayPropertyCatalog.properties[ID]
	}
}
_gitOverlayManifestCoversCatalog: {
	for ID, _ in gitOverlayPropertyCatalog.properties {
		"\(ID)": gitOverlayProperties[ID]
	}
}

#GitOverlayQualificationReport: close({
	schema:         "kernel.git-overlay-qualification-report.v0"
	baseRevision:   #GitObjectID
	hydratorDigest: #Digest

	Declared=declaredPropertyIDs: [...#GitOverlayPropertyID]
	generatedPropertyIDs:         Declared
	executedPropertyIDs:          Declared
	reportedPropertyIDs:          Declared

	propertyReport: close({
		schema: "kernel.git-overlay-property-report.v0"
		results: [...close({
			propertyID: #GitOverlayPropertyID
			status:     "passed"
		})]
		_resultIDs: [for result in results {result.propertyID}]
		_unique:    list.UniqueItems(_resultIDs) & true
	})

	_reportJSON: json.Marshal({
		schema:               schema
		baseRevision:         baseRevision
		hydratorDigest:       hydratorDigest
		declaredPropertyIDs:  declaredPropertyIDs
		generatedPropertyIDs: generatedPropertyIDs
		executedPropertyIDs:  executedPropertyIDs
		reportedPropertyIDs:  reportedPropertyIDs
		propertyReport:       propertyReport
	})
})
