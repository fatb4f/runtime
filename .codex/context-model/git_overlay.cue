package contextmodel

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"list"
	pathpkg "path"
)

// Overlay collection always starts from one exact committed revision. Branch,
// tag, and symbolic selectors belong to the committed-snapshot resolver and
// are intentionally absent from this request boundary.
#GitOverlayRequest: close({
	schema:       "kernel.git-overlay-request.v0"
	repositoryID: #GraphID
	path:         #Path | "."
	baseRevision: #GitObjectID
})

#GitOverlayLayer:       "index" | "worktree"
#GitOverlayStatus:      "added" | "modified" | "deleted" | "untracked"
#GitOverlayPresentKind: "blob" | "symlink" | "submodule"

#GitIndexAddedFileOccurrence: close({
	OccurrencePath=path: #Path & !="."
	layer:               "index"
	status:              "added"
	modeChanged:         false

	mode:     #NonEmptyString
	kind:     "blob" | "symlink"
	objectID: #GitObjectID
	size?:    int & >=0

	_pathNormalized: pathpkg.Clean(OccurrencePath) & OccurrencePath
	_modeKnown:      #GitCommittedModeKind[mode]
	_kindCompatible: kind & _modeKnown
})

#GitIndexAddedSubmoduleOccurrence: close({
	OccurrencePath=path: #Path & !="."
	layer:               "index"
	status:              "added"
	modeChanged:         false

	mode:     #NonEmptyString
	kind:     "submodule"
	objectID: #GitObjectID

	_pathNormalized: pathpkg.Clean(OccurrencePath) & OccurrencePath
	_modeKnown:      #GitCommittedModeKind[mode]
	_kindCompatible: kind & _modeKnown
})

#GitIndexModifiedFileOccurrence: close({
	OccurrencePath=path: #Path & !="."
	layer:               "index"
	status:              "modified"
	modeChanged:         bool

	mode:     #NonEmptyString
	kind:     "blob" | "symlink"
	objectID: #GitObjectID
	size?:    int & >=0

	_pathNormalized: pathpkg.Clean(OccurrencePath) & OccurrencePath
	_modeKnown:      #GitCommittedModeKind[mode]
	_kindCompatible: kind & _modeKnown
})

#GitIndexModifiedSubmoduleOccurrence: close({
	OccurrencePath=path: #Path & !="."
	layer:               "index"
	status:              "modified"
	modeChanged:         bool

	mode:     #NonEmptyString
	kind:     "submodule"
	objectID: #GitObjectID

	_pathNormalized: pathpkg.Clean(OccurrencePath) & OccurrencePath
	_modeKnown:      #GitCommittedModeKind[mode]
	_kindCompatible: kind & _modeKnown
})

#GitIndexDeletedOccurrence: close({
	OccurrencePath=path: #Path & !="."
	layer:               "index"
	status:              "deleted"
	modeChanged:         false

	_pathNormalized: pathpkg.Clean(OccurrencePath) & OccurrencePath
})

#GitWorktreeModifiedFileOccurrence: close({
	OccurrencePath=path: #Path & !="."
	layer:               "worktree"
	status:              "modified"
	modeChanged:         bool

	mode:     #NonEmptyString
	kind:     "blob" | "symlink"
	objectID: #GitObjectID
	size?:    int & >=0

	_pathNormalized: pathpkg.Clean(OccurrencePath) & OccurrencePath
	_modeKnown:      #GitCommittedModeKind[mode]
	_kindCompatible: kind & _modeKnown
})

#GitWorktreeModifiedSubmoduleOccurrence: close({
	OccurrencePath=path: #Path & !="."
	layer:               "worktree"
	status:              "modified"
	modeChanged:         bool

	mode:     #NonEmptyString
	kind:     "submodule"
	objectID: #GitObjectID

	_pathNormalized: pathpkg.Clean(OccurrencePath) & OccurrencePath
	_modeKnown:      #GitCommittedModeKind[mode]
	_kindCompatible: kind & _modeKnown
})

#GitWorktreeUntrackedFileOccurrence: close({
	OccurrencePath=path: #Path & !="."
	layer:               "worktree"
	status:              "untracked"
	modeChanged:         false

	mode:     #NonEmptyString
	kind:     "blob" | "symlink"
	objectID: #GitObjectID
	size?:    int & >=0

	_pathNormalized: pathpkg.Clean(OccurrencePath) & OccurrencePath
	_modeKnown:      #GitCommittedModeKind[mode]
	_kindCompatible: kind & _modeKnown
})

#GitWorktreeUntrackedSubmoduleOccurrence: close({
	OccurrencePath=path: #Path & !="."
	layer:               "worktree"
	status:              "untracked"
	modeChanged:         false

	mode:     #NonEmptyString
	kind:     "submodule"
	objectID: #GitObjectID

	_pathNormalized: pathpkg.Clean(OccurrencePath) & OccurrencePath
	_modeKnown:      #GitCommittedModeKind[mode]
	_kindCompatible: kind & _modeKnown
})

#GitWorktreeDeletedOccurrence: close({
	OccurrencePath=path: #Path & !="."
	layer:               "worktree"
	status:              "deleted"
	modeChanged:         false

	_pathNormalized: pathpkg.Clean(OccurrencePath) & OccurrencePath
})

#GitOverlayPresentOccurrence:
	#GitIndexAddedFileOccurrence |
		#GitIndexAddedSubmoduleOccurrence |
		#GitIndexModifiedFileOccurrence |
		#GitIndexModifiedSubmoduleOccurrence |
		#GitWorktreeModifiedFileOccurrence |
		#GitWorktreeModifiedSubmoduleOccurrence |
		#GitWorktreeUntrackedFileOccurrence |
		#GitWorktreeUntrackedSubmoduleOccurrence

#GitOverlayDeletedOccurrence:
	#GitIndexDeletedOccurrence |
		#GitWorktreeDeletedOccurrence

#GitIndexOverlayOccurrence:
	#GitIndexAddedFileOccurrence |
		#GitIndexAddedSubmoduleOccurrence |
		#GitIndexModifiedFileOccurrence |
		#GitIndexModifiedSubmoduleOccurrence |
		#GitIndexDeletedOccurrence

#GitWorktreeOverlayOccurrence:
	#GitWorktreeModifiedFileOccurrence |
		#GitWorktreeModifiedSubmoduleOccurrence |
		#GitWorktreeUntrackedFileOccurrence |
		#GitWorktreeUntrackedSubmoduleOccurrence |
		#GitWorktreeDeletedOccurrence

#GitIndexOverlay: close({
	schema:       "kernel.git-index-overlay.v0"
	repositoryID: #GraphID
	baseRevision: #GitObjectID

	Occurrences=occurrences: [...#GitIndexOverlayOccurrence]
	_occurrencePaths:        [for occurrence in Occurrences {occurrence.path}]
	_pathsUnique:            list.UniqueItems(_occurrencePaths) & true
	_pathsSorted:            list.IsSortedStrings(_occurrencePaths) & true
})

#GitWorktreeOverlay: close({
	schema:       "kernel.git-worktree-overlay.v0"
	repositoryID: #GraphID
	baseRevision: #GitObjectID

	Occurrences=occurrences: [...#GitWorktreeOverlayOccurrence]
	_occurrencePaths:        [for occurrence in Occurrences {occurrence.path}]
	_pathsUnique:            list.UniqueItems(_occurrencePaths) & true
	_pathsSorted:            list.IsSortedStrings(_occurrencePaths) & true
})

#GitOverlayObservation: close({
	schema: "kernel.git-overlay-observation.v0"

	RepositoryID=repositoryID: #GraphID
	BaseRevision=baseRevision: #GitObjectID
	baseTree:                  #GitObjectID

	index: #GitIndexOverlay & {
		repositoryID: RepositoryID
		baseRevision: BaseRevision
	}
	worktree: #GitWorktreeOverlay & {
		repositoryID: RepositoryID
		baseRevision: BaseRevision
	}

	hydrator: close({
		identity: #GraphID
		digest:   #Digest
	})
})

#GitOverlayProjection: close({
	schema: "kernel.git-overlay-projection.v0"

	Committed=committed:       #GitCommittedSnapshotProjection
	Observation=observation:   #GitOverlayObservation
	SchemaDigest=schemaDigest: #Digest
	PolicyDigest=policyDigest: #Digest

	// The overlay can only apply to the immutable committed graph that resolved
	// the same repository, commit, tree, schema, and authority policy.
	_repositoryBinding: Observation.repositoryID & Committed.observation.repositoryID
	_revisionBinding:   Observation.baseRevision & Committed.observation.resolvedRevision
	_treeBinding:       Observation.baseTree & Committed.observation.rootTree
	_schemaBinding:     SchemaDigest & Committed.schemaDigest
	_policyBinding:     PolicyDigest & Committed.policyDigest

	_observationJSON:              json.Marshal(Observation)
	observationDigest:             "sha256:" + hex.Encode(sha256.Sum256(_observationJSON))
	_indexJSON:                    json.Marshal(Observation.index)
	IndexDigest=indexDigest:       "sha256:" + hex.Encode(sha256.Sum256(_indexJSON))
	_worktreeJSON:                 json.Marshal(Observation.worktree)
	WorktreeDigest=worktreeDigest: "sha256:" + hex.Encode(sha256.Sum256(_worktreeJSON))

	_moduleID:           "sha256:" + hex.Encode(sha256.Sum256("git-module\u0000" + Observation.repositoryID))
	_rootNamespaceID:    "sha256:" + hex.Encode(sha256.Sum256("git-root-namespace\u0000" + Observation.repositoryID))
	_indexEvidenceID:    "sha256:" + hex.Encode(sha256.Sum256("git-index-overlay-evidence\u0000" + indexDigest))
	_worktreeEvidenceID: "sha256:" + hex.Encode(sha256.Sum256("git-worktree-overlay-evidence\u0000" + worktreeDigest))
	_overlaySnapshotID: "sha256:" + hex.Encode(sha256.Sum256(
		"git-overlay-projection\u0000" + Committed.graph.snapshotID + "\u0000" + observationDigest + "\u0000" + SchemaDigest + "\u0000" + PolicyDigest + "\u0000" + Observation.hydrator.digest,
	))

	_indexCount:    len(Observation.index.occurrences)
	_worktreeCount: len(Observation.worktree.occurrences)
	_overlayCount:  _indexCount + _worktreeCount

	Graph=graph: #ContextGraphSnapshot
	if _overlayCount == 0 {
		graph: Committed.graph
	}
	if _overlayCount > 0 {
		graph: {
			snapshotID: _overlaySnapshotID
			modules:    Committed.graph.modules
			namespaces: Committed.graph.namespaces

			members: Committed.graph.members & {
				for occurrence in Observation.index.occurrences {
					let occurrenceID = "sha256:" + hex.Encode(sha256.Sum256(
						Observation.repositoryID + "\u0000" + occurrence.path,
					))
					let layerOccurrenceID = "sha256:" + hex.Encode(sha256.Sum256(
						Observation.repositoryID + "\u0000" + Observation.baseRevision.format + "\u0000" + Observation.baseRevision.hex + "\u0000index\u0000" + occurrence.path,
					))
					"\(layerOccurrenceID)": {
						moduleID:    _moduleID
						namespaceID: _rootNamespaceID
						name:        pathpkg.Base(occurrence.path)
						kind:        "file"
						path:        occurrence.path
						source: {
							kind:       "git-index-overlay"
							repository: Observation.repositoryID
							revision:   Observation.baseRevision.format + ":" + Observation.baseRevision.hex
							path:       occurrence.path
							if occurrence.status != "deleted" {
								contentDigest: "git-" + occurrence.objectID.format + ":" + occurrence.objectID.hex
							}
						}
						properties: {
							occurrenceIdentity:      occurrenceID
							layerOccurrenceIdentity: layerOccurrenceID
							overlayLayer:            "index"
							overlayStatus:           occurrence.status
							modeChanged:             occurrence.modeChanged
							if occurrence.status != "deleted" {
								contentIdentity: "git-object:" + occurrence.objectID.format + ":" + occurrence.objectID.hex
								gitMode:         occurrence.mode
								gitKind:         occurrence.kind
								if occurrence.size != _|_ {
									gitSizeBytes: occurrence.size
								}
							}
						}
					}
				}
				for occurrence in Observation.worktree.occurrences {
					let occurrenceID = "sha256:" + hex.Encode(sha256.Sum256(
						Observation.repositoryID + "\u0000" + occurrence.path,
					))
					let layerOccurrenceID = "sha256:" + hex.Encode(sha256.Sum256(
						Observation.repositoryID + "\u0000" + Observation.baseRevision.format + "\u0000" + Observation.baseRevision.hex + "\u0000worktree\u0000" + occurrence.path,
					))
					"\(layerOccurrenceID)": {
						moduleID:    _moduleID
						namespaceID: _rootNamespaceID
						name:        pathpkg.Base(occurrence.path)
						kind:        "file"
						path:        occurrence.path
						source: {
							kind:       "git-worktree-overlay"
							repository: Observation.repositoryID
							revision:   Observation.baseRevision.format + ":" + Observation.baseRevision.hex
							path:       occurrence.path
							if occurrence.status != "deleted" {
								contentDigest: "git-" + occurrence.objectID.format + ":" + occurrence.objectID.hex
							}
						}
						properties: {
							occurrenceIdentity:      occurrenceID
							layerOccurrenceIdentity: layerOccurrenceID
							overlayLayer:            "worktree"
							overlayStatus:           occurrence.status
							modeChanged:             occurrence.modeChanged
							if occurrence.status != "deleted" {
								contentIdentity: "git-object:" + occurrence.objectID.format + ":" + occurrence.objectID.hex
								gitMode:         occurrence.mode
								gitKind:         occurrence.kind
								if occurrence.size != _|_ {
									gitSizeBytes: occurrence.size
								}
							}
						}
					}
				}
			}

			relationships: Committed.graph.relationships & {
				for occurrence in Observation.index.occurrences {
					let layerOccurrenceID = "sha256:" + hex.Encode(sha256.Sum256(
						Observation.repositoryID + "\u0000" + Observation.baseRevision.format + "\u0000" + Observation.baseRevision.hex + "\u0000index\u0000" + occurrence.path,
					))
					let relationshipID = "sha256:" + hex.Encode(sha256.Sum256("git-overlay\u0000" + _rootNamespaceID + "\u0000" + layerOccurrenceID))
					"\(relationshipID)": {
						subject:     {kind: "namespace", id: _rootNamespaceID}
						predicate:   "occurs_as"
						object:      {kind: "member", id: layerOccurrenceID}
						evidenceIDs: [_indexEvidenceID]
					}
				}
				for occurrence in Observation.worktree.occurrences {
					let layerOccurrenceID = "sha256:" + hex.Encode(sha256.Sum256(
						Observation.repositoryID + "\u0000" + Observation.baseRevision.format + "\u0000" + Observation.baseRevision.hex + "\u0000worktree\u0000" + occurrence.path,
					))
					let relationshipID = "sha256:" + hex.Encode(sha256.Sum256("git-overlay\u0000" + _rootNamespaceID + "\u0000" + layerOccurrenceID))
					"\(relationshipID)": {
						subject:     {kind: "namespace", id: _rootNamespaceID}
						predicate:   "occurs_as"
						object:      {kind: "member", id: layerOccurrenceID}
						evidenceIDs: [_worktreeEvidenceID]
					}
				}
			}

			evidence: Committed.graph.evidence & {
				if _indexCount > 0 {
					"\(_indexEvidenceID)": {
						kind:     "observation"
						subject:  {kind: "module", id: _moduleID}
						producer: null
						source: {
							kind:          "git-index-overlay"
							repository:    Observation.repositoryID
							revision:      Observation.baseRevision.format + ":" + Observation.baseRevision.hex
							path:          "."
							contentDigest: indexDigest
						}
						authority:     "candidate"
						payloadDigest: indexDigest
						diagnostics:   []
						properties: {
							overlayLayer:     "index"
							hydratorIdentity: Observation.hydrator.identity
							hydratorDigest:   Observation.hydrator.digest
						}
					}
				}
				if _worktreeCount > 0 {
					"\(_worktreeEvidenceID)": {
						kind:     "observation"
						subject:  {kind: "module", id: _moduleID}
						producer: null
						source: {
							kind:          "git-worktree-overlay"
							repository:    Observation.repositoryID
							revision:      Observation.baseRevision.format + ":" + Observation.baseRevision.hex
							path:          "."
							contentDigest: worktreeDigest
						}
						authority:     "candidate"
						payloadDigest: worktreeDigest
						diagnostics:   []
						properties: {
							overlayLayer:     "worktree"
							hydratorIdentity: Observation.hydrator.identity
							hydratorDigest:   Observation.hydrator.digest
						}
					}
				}
			}

			provenance: {
				authorityDigest: PolicyDigest
				schemaDigest:    SchemaDigest
				hydratorDigest:  Observation.hydrator.digest
				baseRevision:    Observation.baseRevision.format + ":" + Observation.baseRevision.hex
				baseTree:        Observation.baseTree.format + ":" + Observation.baseTree.hex
				indexDigest:     IndexDigest
				worktreeDigest:  WorktreeDigest
			}
		}
	}

	collected: close({
		if _indexCount > 0 {
			index: #ContextCollectedEvidenceEnvelope & {
				state: {
					evidenceID:         _indexEvidenceID
					snapshotID:         Graph.snapshotID
					evidence:           Graph.evidence[_indexEvidenceID]
					effectiveAuthority: "candidate"
				}
			}
		}
		if _worktreeCount > 0 {
			worktree: #ContextCollectedEvidenceEnvelope & {
				state: {
					evidenceID:         _worktreeEvidenceID
					snapshotID:         Graph.snapshotID
					evidence:           Graph.evidence[_worktreeEvidenceID]
					effectiveAuthority: "candidate"
				}
			}
		}
	})
})
