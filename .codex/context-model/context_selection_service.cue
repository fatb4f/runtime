package contextmodel

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"list"
	"strings"
)

// The application boundary is deliberately smaller than the workbook request.
// A caller may propose roots, but may not submit selected graph state.
#ContextApplicationRequest: close({
	schema:     "dotfiles.context-application-request.v0"
	requestID:  #ID
	repository: #NonEmptyString
	revision:   #NonEmptyString

	allowedPaths: [#Path | ".", ...#Path | "."]
	overlayMode:  "disabled" | "required" | "auto"
	// A service request must carry at least one explicit root. The proposal may
	// add roots, but it never supplies the only success-path seed.
	roots: close({
		memberIDs:    [...#GraphID]
		namespaceIDs: [...#GraphID]
		pathPrefixes: [...#Path | "."]

		_explicitRoot: memberIDs[0] | namespaceIDs[0] | pathPrefixes[0]
	})
})

#ContextRootProposal: close({
	schema:     "dotfiles.context-root-proposal.v0"
	requestID:  #ID
	snapshotID: #Digest

	memberIDs:    [...#GraphID]
	namespaceIDs: [...#GraphID]
	pathPrefixes: [...#Path | "."]
})

#ContextRootCatalog: close({
	Schema=schema:         "dotfiles.context-root-catalog.v0"
	RequestID=requestID:   #ID
	SnapshotID=snapshotID: #Digest

	MemberIDs=memberIDs:       [...#GraphID]
	NamespaceIDs=namespaceIDs: [...#GraphID]
	Paths=paths:               [...#Path]

	_membersBounded:    len(memberIDs) <= 2048
	_namespacesBounded: len(namespaceIDs) <= 256
	_pathsBounded:      len(paths) <= 2048
	_canonicalBytes: json.Marshal({
		schema:       Schema
		requestID:    RequestID
		snapshotID:   SnapshotID
		memberIDs:    MemberIDs
		namespaceIDs: NamespaceIDs
		paths:        Paths
	})
	_bytesBounded: len(_canonicalBytes) <= 262144
})

#ContextSelectionLimits: close({
	maxDepth:             8
	maxRoots:             64
	maxModules:           8
	maxNamespaces:        64
	maxMembers:           256
	maxEntities:          320
	maxFiles:             32
	maxSelectedFileBytes: 1048576
	maxRelationships:     512
	maxEvidence:          128
	maxPredicates:        8
	maxPacketBytes:       65536
})

#ContextSelectionPolicy: close({
	schema:     "dotfiles.context-selection-policy.v0"
	predicates: [...#ContextPredicate]
	limits:     #ContextSelectionLimits

	// v0 traversal is intentionally a one-element allowlist. Enriched
	// relationships remain graph facts but cannot widen this selection.
	_predicateLimit: len(predicates) <= limits.maxPredicates
	_predicatesKnown: [for predicate in predicates {
		predicate & "contains"
	}]
})

#GitEffectiveOccurrence: close({
	path:   #Path
	layer:  "committed" | "index" | "worktree"
	status: "present" | "deleted"
	kind:   "blob" | "symlink" | "tree" | "submodule" | "tombstone"

	memberID:      #GraphID
	evidenceID:    #GraphID
	gitSizeBytes?: int & >=0
})

#GitEffectivePathView: close({
	schema:     "dotfiles.git-effective-path-view.v0"
	snapshotID: #Digest
	paths:      [...#GitEffectiveOccurrence]

	_fileSizes: [for occurrence in paths
	if occurrence.status == "present" &&
		(occurrence.kind == "blob" || occurrence.kind == "symlink") {
		occurrence.gitSizeBytes & int & >=0
	}]
})

#GitPathLayerOccurrence: close({
	path:          #Path
	status:        "present" | "deleted"
	kind:          "blob" | "symlink" | "tree" | "submodule" | "tombstone"
	memberID:      #GraphID
	evidenceID:    #GraphID
	gitSizeBytes?: int & >=0
})

// The orchestrator calculates the candidate path union. CUE proves that it is
// sorted, unique, complete, and that every projected winner follows Git layer
// precedence. A deletion is a winner, not absence.
#GitEffectivePathEvaluation: close({
	SnapshotID=snapshotID: #Digest
	AllPaths=allPaths:     [...#Path]
	Committed=committed:   [...#GitPathLayerOccurrence]
	Index=index:           [...#GitPathLayerOccurrence]
	Worktree=worktree:     [...#GitPathLayerOccurrence]

	_committedPaths:  [for occurrence in Committed {occurrence.path}]
	_indexPaths:      [for occurrence in Index {occurrence.path}]
	_worktreePaths:   [for occurrence in Worktree {occurrence.path}]
	_committedSorted: list.IsSortedStrings(_committedPaths) & true
	_indexSorted:     list.IsSortedStrings(_indexPaths) & true
	_worktreeSorted:  list.IsSortedStrings(_worktreePaths) & true
	_committedUnique: list.UniqueItems(_committedPaths) & true
	_indexUnique:     list.UniqueItems(_indexPaths) & true
	_worktreeUnique:  list.UniqueItems(_worktreePaths) & true

	_allObservedPaths: [
		for occurrence in Committed {occurrence.path},
		for occurrence in Index {occurrence.path},
		for occurrence in Worktree {occurrence.path},
	]
	_pathsSorted: list.IsSortedStrings(AllPaths) & true
	_pathsUnique: list.UniqueItems(AllPaths) & true
	_pathCoverage: [for pathValue in AllPaths {
		[for observed in _allObservedPaths if observed == pathValue {observed}] & [_, ...]
	}]
	_observationCoverage: [for observed in _allObservedPaths {
		[for pathValue in AllPaths if pathValue == observed {pathValue}] & [_, ...]
	}]

	view: #GitEffectivePathView & {
		snapshotID: SnapshotID
		paths: [for pathValue in AllPaths {
			let committedMatches = [for occurrence in Committed if occurrence.path == pathValue {occurrence}]
			let indexMatches = [for occurrence in Index if occurrence.path == pathValue {occurrence}]
			let worktreeMatches = [for occurrence in Worktree if occurrence.path == pathValue {occurrence}]
			if len(worktreeMatches) > 0 {
				worktreeMatches[0] & {layer: "worktree"}
			}
			if len(worktreeMatches) == 0 && len(indexMatches) > 0 {
				indexMatches[0] & {layer: "index"}
			}
			if len(worktreeMatches) == 0 && len(indexMatches) == 0 {
				committedMatches[0] & {layer: "committed"}
			}
		}]
	}
})

#ContextTraversalRecord: close({
	entity:      #ContextEntityRef
	distance:    int & >=0 & <=8
	direction:   "root" | "outgoing" | "incoming"
	predecessor: #GraphID | null
})

#ContextSelectionFrontier: close({
	distance: int & >=0 & <=8
	entities: [...#ContextTraversalRecord]
})

#ContextTraversalCandidates: {
	Snapshot=snapshot:     #ContextGraphSnapshot
	Predicates=predicates: [...#ContextPredicate]
	Previous=previous:     [...#ContextTraversalRecord]
	Visited=visited:       [...#ContextTraversalRecord]

	candidates: {
		for _, relationship in Snapshot.relationships
		if len([for record in Previous
		if record.entity == relationship.subject {record}]) > 0 &&
			len([for predicate in Predicates
			if predicate == relationship.predicate {predicate}]) > 0 &&
			len([for record in Visited
			if record.entity == relationship.object {record}]) == 0 {
			"\(relationship.object.kind):\(relationship.object.id)": relationship.object
		}
		for _, relationship in Snapshot.relationships
		if len([for record in Previous
		if record.entity == relationship.object {record}]) > 0 &&
			len([for predicate in Predicates
			if predicate == relationship.predicate {predicate}]) > 0 &&
			len([for record in Visited
			if record.entity == relationship.subject {record}]) == 0 {
			"\(relationship.subject.kind):\(relationship.subject.id)": relationship.subject
		}
	}
}

#ContextTraversalStep: {
	Snapshot=snapshot:     #ContextGraphSnapshot
	Predicates=predicates: [...#ContextPredicate]
	Previous=previous:     [...#ContextTraversalRecord]
	Visited=visited:       [...#ContextTraversalRecord]
	Distance=distance:     int & >=1 & <=8

	_candidateEvaluation: #ContextTraversalCandidates & {
		snapshot:   Snapshot
		predicates: Predicates
		previous:   Previous
		visited:    Visited
	}
	records: [for _, candidateEntity in _candidateEvaluation.candidates {
		let predecessors = list.SortStrings([for relationshipID, relationship in Snapshot.relationships
		if len([for predicate in Predicates
		if predicate == relationship.predicate {predicate}]) > 0 &&
			((relationship.object == candidateEntity &&
				len([for record in Previous
				if record.entity == relationship.subject {record}]) > 0) ||
				(relationship.subject == candidateEntity &&
					len([for record in Previous
					if record.entity == relationship.object {record}]) > 0)) {
			relationshipID
		}])
		let predecessorRelationshipID = predecessors[0]
		let predecessorRelationship = Snapshot.relationships[predecessorRelationshipID]
		{
			entity:      candidateEntity
			distance:    Distance
			predecessor: predecessorRelationshipID
			if predecessorRelationship.object == candidateEntity {
				direction: "outgoing"
			}
			if predecessorRelationship.subject == candidateEntity {
				direction: "incoming"
			}
		}
	}]
}

#ContextTraversalDepthCompletion: {
	Snapshot=snapshot:     #ContextGraphSnapshot
	Predicates=predicates: [...#ContextPredicate]
	Visited=visited:       [...#ContextTraversalRecord]

	_candidateEvaluation: #ContextTraversalCandidates & {
		snapshot:   Snapshot
		predicates: Predicates
		previous:   Visited
		visited:    Visited
	}
	candidates: _candidateEvaluation.candidates
	complete:   (len(candidates) == 0) & true
}

#ContextSelectionProof: close({
	schema:     "dotfiles.context-selection-proof.v0"
	snapshotID: #Digest

	frontier0: #ContextSelectionFrontier & {distance: 0}
	frontier1: #ContextSelectionFrontier & {distance: 1}
	frontier2: #ContextSelectionFrontier & {distance: 2}
	frontier3: #ContextSelectionFrontier & {distance: 3}
	frontier4: #ContextSelectionFrontier & {distance: 4}
	frontier5: #ContextSelectionFrontier & {distance: 5}
	frontier6: #ContextSelectionFrontier & {distance: 6}
	frontier7: #ContextSelectionFrontier & {distance: 7}
	frontier8: #ContextSelectionFrontier & {distance: 8}

	selected:        [...#ContextEntityRef]
	relationshipIDs: [...#GraphID]
	evidenceIDs:     [...#GraphID]
	effectiveFiles:  [...#Path]

	counters: close({
		modules:       int & >=0
		namespaces:    int & >=0
		members:       int & >=0
		entities:      int & >=0
		files:         int & >=0
		fileBytes:     int & >=0
		relationships: int & >=0
		evidence:      int & >=0
	})
	contextDigest: #Digest
	packetDigest:  #Digest
})

#ContextPacketEvidenceAlias: close({
	graphEvidenceID:  #GraphID
	packetEvidenceID: #NonEmptyString & =~"^evidence\\..+$"
})

#ContextPacketV0Projection: close({
	adapterVersion: "context-packet-v0-adapter.v1"
	aliases:        [...#ContextPacketEvidenceAlias]
	packet:         #ContextPacket

	_aliasDerivations: [for alias in aliases {
		let digest = hex.Encode(sha256.Sum256(alias.graphEvidenceID))
		alias.packetEvidenceID & "evidence.\(digest)"
	}]
})

#ContextDigestEvaluation: {
	AdapterVersion=adapterVersion:       "context-packet-v0-adapter.v1"
	Request=request:                     #ContextApplicationRequest
	Proposal=proposal:                   #ContextRootProposal
	Policy=policy:                       #ContextSelectionPolicy
	EffectivePathView=effectivePathView: #GitEffectivePathView
	TraversalRecords=traversalRecords:   [...#ContextTraversalRecord]
	SelectedEntities=selectedEntities:   [...#ContextEntityRef]
	RelationshipIDs=relationshipIDs:     [...#GraphID]
	EvidenceIDs=evidenceIDs:             [...#GraphID]
	EffectiveFiles=effectiveFiles:       [...#Path]
	EvidenceAliases=evidenceAliases:     [...#ContextPacketEvidenceAlias]

	envelope: {
		schema:            "dotfiles.context-digest-envelope.v1"
		adapterVersion:    AdapterVersion
		request:           Request
		proposal:          Proposal
		policy:            Policy
		effectivePathView: EffectivePathView
		traversalRecords:  TraversalRecords
		selectedEntities:  SelectedEntities
		relationshipIDs:   RelationshipIDs
		evidenceIDs:       EvidenceIDs
		effectiveFiles:    EffectiveFiles
		evidenceAliases:   EvidenceAliases
	}
	canonicalBytes: json.Marshal(envelope)
	contextDigest:  "sha256:" + hex.Encode(sha256.Sum256(canonicalBytes))
}

#ContextRootSelectionEvaluation: {
	Request=request:             #ContextApplicationRequest
	Proposal=proposal:           #ContextRootProposal
	Policy=policy:               #ContextSelectionPolicy
	Snapshot=snapshot:           #ContextGraphSnapshot
	EffectiveView=effectiveView: #GitEffectivePathView

	_requestProposal:  Request.requestID & Proposal.requestID
	_proposalSnapshot: Proposal.snapshotID & Snapshot.snapshotID
	_viewSnapshot:     EffectiveView.snapshotID & Snapshot.snapshotID

	rootCatalog: #ContextRootCatalog & {
		requestID:  Request.requestID
		snapshotID: Snapshot.snapshotID
		memberIDs: [for memberID, member in Snapshot.members
		if member.path != _|_ &&
			len([for allowed in Request.allowedPaths
			if allowed == "." || member.path == allowed ||
				strings.HasPrefix(member.path, allowed + "/") {allowed}]) > 0 {
			memberID
		}]
		namespaceIDs: [for id, _ in Snapshot.namespaces {id}]
		paths: [for occurrence in EffectiveView.paths
		if occurrence.status == "present" &&
			len([for allowed in Request.allowedPaths
			if allowed == "." || occurrence.path == allowed ||
				strings.HasPrefix(occurrence.path, allowed + "/") {allowed}]) > 0 {
			occurrence.path
		}]
	}

	_requestMembersCatalogued: [for root in Request.roots.memberIDs {
		[for id in rootCatalog.memberIDs if id == root {id}] & [_, ...]
	}]
	_proposalMembersCatalogued: [for root in Proposal.memberIDs {
		[for id in rootCatalog.memberIDs if id == root {id}] & [_, ...]
	}]
	_requestNamespacesCatalogued: [for root in Request.roots.namespaceIDs {
		[for id in rootCatalog.namespaceIDs if id == root {id}] & [_, ...]
	}]
	_proposalNamespacesCatalogued: [for root in Proposal.namespaceIDs {
		[for id in rootCatalog.namespaceIDs if id == root {id}] & [_, ...]
	}]
	_requestPrefixesBounded: [for root in Request.roots.pathPrefixes {
		let prefix = root
		allowedPaths: [for allowed in Request.allowedPaths
		if allowed == "." || prefix == allowed || strings.HasPrefix(prefix, allowed + "/") {allowed}] & [_, ...]
		matchedPaths: [for path in rootCatalog.paths
		if prefix == "." || path == prefix || strings.HasPrefix(path, prefix + "/") {path}] & [_, ...]
	}]
	_proposalPrefixesBounded: [for root in Proposal.pathPrefixes {
		let prefix = root
		allowedPaths: [for allowed in Request.allowedPaths
		if allowed == "." || prefix == allowed || strings.HasPrefix(prefix, allowed + "/") {allowed}] & [_, ...]
		matchedPaths: [for path in rootCatalog.paths
		if prefix == "." || path == prefix || strings.HasPrefix(path, prefix + "/") {path}] & [_, ...]
	}]

	roots: {
		for memberID in Request.roots.memberIDs {
			"member:\(memberID)": {kind: "member", id: memberID}
		}
		for memberID in Proposal.memberIDs {
			"member:\(memberID)": {kind: "member", id: memberID}
		}
		for namespaceID in Request.roots.namespaceIDs {
			"namespace:\(namespaceID)": {kind: "namespace", id: namespaceID}
		}
		for namespaceID in Proposal.namespaceIDs {
			"namespace:\(namespaceID)": {kind: "namespace", id: namespaceID}
		}
		for prefix in Request.roots.pathPrefixes {
			for occurrence in EffectiveView.paths
			if occurrence.status == "present" &&
				(prefix == "." || occurrence.path == prefix ||
					strings.HasPrefix(occurrence.path, prefix + "/")) {
				"member:\(occurrence.memberID)": {kind: "member", id: occurrence.memberID}
			}
		}
		for prefix in Proposal.pathPrefixes {
			for occurrence in EffectiveView.paths
			if occurrence.status == "present" &&
				(prefix == "." || occurrence.path == prefix ||
					strings.HasPrefix(occurrence.path, prefix + "/")) {
				"member:\(occurrence.memberID)": {kind: "member", id: occurrence.memberID}
			}
		}
	}

	rootSpecificationCount: len(Request.roots.memberIDs) +
		len(Request.roots.namespaceIDs) +
		len(Request.roots.pathPrefixes) +
		len(Proposal.memberIDs) +
		len(Proposal.namespaceIDs) +
		len(Proposal.pathPrefixes)
	_rootsBounded: (rootSpecificationCount <= Policy.limits.maxRoots) & true
}

#ContextEffectiveFileSelection: {
	EffectiveView=effectiveView: #GitEffectivePathView
	Selected=selected:           [...#ContextEntityRef]

	_selectedSet: {
		for entity in Selected {"\(entity.kind):\(entity.id)": true}
	}
	fileOccurrences: {
		for occurrence in EffectiveView.paths
		if occurrence.status == "present" &&
			(occurrence.kind == "blob" || occurrence.kind == "symlink") &&
			_selectedSet["member:\(occurrence.memberID)"] == true {
			"\(occurrence.path)": occurrence
		}
	}
	files: [for path, _ in fileOccurrences {path}]
}

// The common evaluation accepts only authoritative inputs. Every frontier,
// selected entity, induced relationship, evidence reference, counter, alias,
// and digest below is a projection. Callers cannot submit any of those values.
#ContextSelectionEvaluation: {
	Request=request:   #ContextApplicationRequest
	Proposal=proposal: #ContextRootProposal
	Policy=policy:     #ContextSelectionPolicy
	Snapshot=snapshot: #ContextGraphSnapshot
	EffectivePathEvaluation=effectivePathEvaluation: #GitEffectivePathEvaluation & {
		snapshotID: Snapshot.snapshotID
	}
	EffectiveView=effectiveView: EffectivePathEvaluation.view

	_rootEvaluation: #ContextRootSelectionEvaluation & {
		request:       Request
		proposal:      Proposal
		policy:        Policy
		snapshot:      Snapshot
		effectiveView: EffectiveView
	}
	rootCatalog: _rootEvaluation.rootCatalog
	_rootSet:    _rootEvaluation.roots

	_frontier0: #ContextSelectionFrontier & {
		distance: 0
		entities: [for _, rootEntity in _rootSet {
			entity:      rootEntity
			distance:    0
			direction:   "root"
			predecessor: null
		}]
	}
	_step1: #ContextTraversalStep & {
		snapshot:   Snapshot
		predicates: Policy.predicates
		previous:   _frontier0.entities
		visited:    _frontier0.entities
		distance:   1
	}
	_frontier1: #ContextSelectionFrontier & {distance: 1, entities: _step1.records}
	_step2: #ContextTraversalStep & {
		snapshot:   Snapshot
		predicates: Policy.predicates
		previous:   _frontier1.entities
		visited:    list.Concat([_frontier0.entities, _frontier1.entities])
		distance:   2
	}
	_frontier2: #ContextSelectionFrontier & {distance: 2, entities: _step2.records}
	_step3: #ContextTraversalStep & {
		snapshot:   Snapshot
		predicates: Policy.predicates
		previous:   _frontier2.entities
		visited:    list.Concat([_frontier0.entities, _frontier1.entities, _frontier2.entities])
		distance:   3
	}
	_frontier3: #ContextSelectionFrontier & {distance: 3, entities: _step3.records}
	_step4: #ContextTraversalStep & {
		snapshot:   Snapshot
		predicates: Policy.predicates
		previous:   _frontier3.entities
		visited:    list.Concat([_frontier0.entities, _frontier1.entities, _frontier2.entities, _frontier3.entities])
		distance:   4
	}
	_frontier4: #ContextSelectionFrontier & {distance: 4, entities: _step4.records}
	_step5: #ContextTraversalStep & {
		snapshot:   Snapshot
		predicates: Policy.predicates
		previous:   _frontier4.entities
		visited:    list.Concat([_frontier0.entities, _frontier1.entities, _frontier2.entities, _frontier3.entities, _frontier4.entities])
		distance:   5
	}
	_frontier5: #ContextSelectionFrontier & {distance: 5, entities: _step5.records}
	_step6: #ContextTraversalStep & {
		snapshot:   Snapshot
		predicates: Policy.predicates
		previous:   _frontier5.entities
		visited:    list.Concat([_frontier0.entities, _frontier1.entities, _frontier2.entities, _frontier3.entities, _frontier4.entities, _frontier5.entities])
		distance:   6
	}
	_frontier6: #ContextSelectionFrontier & {distance: 6, entities: _step6.records}
	_step7: #ContextTraversalStep & {
		snapshot:   Snapshot
		predicates: Policy.predicates
		previous:   _frontier6.entities
		visited:    list.Concat([_frontier0.entities, _frontier1.entities, _frontier2.entities, _frontier3.entities, _frontier4.entities, _frontier5.entities, _frontier6.entities])
		distance:   7
	}
	_frontier7: #ContextSelectionFrontier & {distance: 7, entities: _step7.records}
	_step8: #ContextTraversalStep & {
		snapshot:   Snapshot
		predicates: Policy.predicates
		previous:   _frontier7.entities
		visited:    list.Concat([_frontier0.entities, _frontier1.entities, _frontier2.entities, _frontier3.entities, _frontier4.entities, _frontier5.entities, _frontier6.entities, _frontier7.entities])
		distance:   8
	}
	_frontier8: #ContextSelectionFrontier & {distance: 8, entities: _step8.records}

	_records: list.Concat([
		_frontier0.entities,
		_frontier1.entities,
		_frontier2.entities,
		_frontier3.entities,
		_frontier4.entities,
		_frontier5.entities,
		_frontier6.entities,
		_frontier7.entities,
		_frontier8.entities,
	])
	_depthCompletion: #ContextTraversalDepthCompletion & {
		snapshot:   Snapshot
		predicates: Policy.predicates
		visited:    _records
	}
	_selected: [for record in _records {record.entity}]
	_selectedSet: {
		for entity in _selected {"\(entity.kind):\(entity.id)": true}
	}
	_relationshipSet: {
		for id, relationship in Snapshot.relationships
		if _selectedSet["\(relationship.subject.kind):\(relationship.subject.id)"] == true &&
			_selectedSet["\(relationship.object.kind):\(relationship.object.id)"] == true &&
			len([for predicate in Policy.predicates
			if predicate == relationship.predicate {predicate}]) > 0 {
			"\(id)": relationship
		}
	}
	_relationshipIDs: [for id, _ in _relationshipSet {id}]
	_evidenceSet: {
		for _, relationship in _relationshipSet {
			for evidenceID in relationship.evidenceIDs {
				"\(evidenceID)": Snapshot.evidence[evidenceID]
			}
		}
	}
	_evidenceIDs: [for id, _ in _evidenceSet {id}]
	_effectiveFileSelection: #ContextEffectiveFileSelection & {
		effectiveView: EffectiveView
		selected:      _selected
	}
	_effectiveFiles: _effectiveFileSelection.files
	_selectedFileBytes: list.Sum([for _, occurrence in _effectiveFileSelection.fileOccurrences {
		occurrence.gitSizeBytes
	}])

	_aliasSet: {
		for evidenceID in _evidenceIDs {
			let digest = hex.Encode(sha256.Sum256(evidenceID))
			"\(evidenceID)": {
				graphEvidenceID:  evidenceID
				packetEvidenceID: "evidence.\(digest)"
			}
		}
	}
	_aliases:           [for _, alias in _aliasSet {alias}]
	_packetEvidenceIDs: [for alias in _aliases {alias.packetEvidenceID}]
	_adapterVersion:    "context-packet-v0-adapter.v1"
	_digestEvaluation: #ContextDigestEvaluation & {
		adapterVersion:    _adapterVersion
		request:           Request
		proposal:          Proposal
		policy:            Policy
		effectivePathView: EffectiveView
		traversalRecords:  _records
		selectedEntities:  _selected
		relationshipIDs:   _relationshipIDs
		evidenceIDs:       _evidenceIDs
		effectiveFiles:    _effectiveFiles
		evidenceAliases:   _aliases
	}
	_contextDigest: _digestEvaluation.contextDigest

	packet: #ContextPacketV0Projection & {
		adapterVersion: _adapterVersion
		aliases:        _aliases
		packet: {
			schema:        "dotfiles.context-packet.v0"
			requestID:     Request.requestID
			contextDigest: _contextDigest
			selected: {
				fragmentIDs: []
				files:       _effectiveFiles
				providerIDs: []
				workflowIDs: []
			}
			evidenceIDs:      _packetEvidenceIDs
			unresolvedGapIDs: []
			provenance: {
				semanticRole:   "workflow"
				artifactClass:  "generated_projection"
				claimAuthority: "candidate"
			}
		}
	}
	_packetCanonical: json.Marshal(packet.packet)
	_packetDigest:    "sha256:" + hex.Encode(sha256.Sum256(_packetCanonical))

	proof: #ContextSelectionProof & {
		schema:          "dotfiles.context-selection-proof.v0"
		snapshotID:      Snapshot.snapshotID
		frontier0:       _frontier0
		frontier1:       _frontier1
		frontier2:       _frontier2
		frontier3:       _frontier3
		frontier4:       _frontier4
		frontier5:       _frontier5
		frontier6:       _frontier6
		frontier7:       _frontier7
		frontier8:       _frontier8
		selected:        _selected
		relationshipIDs: _relationshipIDs
		evidenceIDs:     _evidenceIDs
		effectiveFiles:  _effectiveFiles
		counters: {
			modules:       len([for entity in _selected if entity.kind == "module" {entity}])
			namespaces:    len([for entity in _selected if entity.kind == "namespace" {entity}])
			members:       len([for entity in _selected if entity.kind == "member" {entity}])
			entities:      len(_selected)
			files:         len(_effectiveFiles)
			fileBytes:     _selectedFileBytes
			relationships: len(_relationshipIDs)
			evidence:      len(_evidenceIDs)
		}
		contextDigest: _contextDigest
		packetDigest:  _packetDigest
	}

	if len(_selected) > 0 {
		resolution: #ContextGraphResolution & {
			schema:   "kernel.context-resolution.v0"
			snapshot: Snapshot
			selection: {
				schema:          "kernel.context-selection.v0"
				requestID:       Request.requestID
				snapshotID:      Snapshot.snapshotID
				seedEntities:    [for record in _frontier0.entities {record.entity}]
				selected:        _selected
				relationshipIDs: _relationshipIDs
				evidenceIDs:     _evidenceIDs
				gaps:            {}
				conflicts:       {}
				sufficiency:     "sufficient"
			}
		}
	}

	_modulesBounded:       (proof.counters.modules <= Policy.limits.maxModules) & true
	_namespacesBounded:    (proof.counters.namespaces <= Policy.limits.maxNamespaces) & true
	_membersBounded:       (proof.counters.members <= Policy.limits.maxMembers) & true
	_entitiesBounded:      (proof.counters.entities <= Policy.limits.maxEntities) & true
	_filesBounded:         (proof.counters.files <= Policy.limits.maxFiles) & true
	_fileBytesBounded:     (proof.counters.fileBytes <= Policy.limits.maxSelectedFileBytes) & true
	_relationshipsBounded: (proof.counters.relationships <= Policy.limits.maxRelationships) & true
	_evidenceBounded:      (proof.counters.evidence <= Policy.limits.maxEvidence) & true
	_packetBytesBounded:   (len(_packetCanonical) <= Policy.limits.maxPacketBytes) & true
}

#GitCommittedEffectivePathEvaluation: #GitEffectivePathEvaluation & {
	index:    []
	worktree: []
}

#ContextCommittedSelectionEvaluation: close({
	#ContextSelectionEvaluation
	CommittedProjection=committedProjection: #GitCommittedSnapshotProjection
	CommittedEffectivePathEvaluation=effectivePathEvaluation: #GitCommittedEffectivePathEvaluation & {
		snapshotID: CommittedProjection.graph.snapshotID
		committed: [for occurrence in CommittedProjection.observation.occurrences {
			let computedMemberID = "sha256:" + hex.Encode(sha256.Sum256(
				CommittedProjection.observation.repositoryID + "\u0000" + occurrence.path,
			))
			{
				path:       occurrence.path
				status:     "present"
				kind:       occurrence.kind
				memberID:   computedMemberID
				evidenceID: CommittedProjection.collected.state.evidenceID
				if occurrence.size != _|_ {
					gitSizeBytes: occurrence.size
				}
			}
		}]
		allPaths: [for occurrence in committed {occurrence.path}]
	}
	CommittedSnapshot=snapshot:           CommittedProjection.graph
	CommittedEffectiveView=effectiveView: CommittedEffectivePathEvaluation.view

	_rootEvaluation:         {snapshot: CommittedSnapshot, effectiveView: CommittedEffectiveView}
	_step1:                  {snapshot: CommittedSnapshot}
	_step2:                  {snapshot: CommittedSnapshot}
	_step3:                  {snapshot: CommittedSnapshot}
	_step4:                  {snapshot: CommittedSnapshot}
	_step5:                  {snapshot: CommittedSnapshot}
	_step6:                  {snapshot: CommittedSnapshot}
	_step7:                  {snapshot: CommittedSnapshot}
	_step8:                  {snapshot: CommittedSnapshot}
	_depthCompletion:        {snapshot: CommittedSnapshot}
	_effectiveFileSelection: {effectiveView: CommittedEffectiveView}
	_digestEvaluation:       {effectivePathView: CommittedEffectiveView}
})

#ContextOverlaySelectionEvaluation: close({
	#ContextSelectionEvaluation
	CommittedProjection=committedProjection: #GitCommittedSnapshotProjection
	OverlayProjection=overlayProjection:     #GitOverlayProjection
	_committedBinding:                       OverlayProjection.committed.observationDigest & CommittedProjection.observationDigest
	OverlayEffectivePathEvaluation=effectivePathEvaluation: #GitEffectivePathEvaluation & {
		snapshotID: OverlayProjection.graph.snapshotID
		committed: [for occurrence in CommittedProjection.observation.occurrences {
			let computedMemberID = "sha256:" + hex.Encode(sha256.Sum256(
				CommittedProjection.observation.repositoryID + "\u0000" + occurrence.path,
			))
			{
				path:       occurrence.path
				status:     "present"
				kind:       occurrence.kind
				memberID:   computedMemberID
				evidenceID: CommittedProjection.collected.state.evidenceID
				if occurrence.size != _|_ {
					gitSizeBytes: occurrence.size
				}
			}
		}]
		index: [for occurrence in OverlayProjection.observation.index.occurrences {
			let computedMemberID = "sha256:" + hex.Encode(sha256.Sum256(
				OverlayProjection.observation.repositoryID + "\u0000" +
					OverlayProjection.observation.baseRevision.format + "\u0000" +
					OverlayProjection.observation.baseRevision.hex + "\u0000index\u0000" +
					occurrence.path,
			))
			{
				path: occurrence.path
				if occurrence.status == "deleted" {
					status: "deleted"
					kind:   "tombstone"
				}
				if occurrence.status != "deleted" {
					status: "present"
					kind:   occurrence.kind
				}
				memberID:   computedMemberID
				evidenceID: OverlayProjection.collected.index.state.evidenceID
				if occurrence.size != _|_ {
					gitSizeBytes: occurrence.size
				}
			}
		}]
		worktree: [for occurrence in OverlayProjection.observation.worktree.occurrences {
			let computedMemberID = "sha256:" + hex.Encode(sha256.Sum256(
				OverlayProjection.observation.repositoryID + "\u0000" +
					OverlayProjection.observation.baseRevision.format + "\u0000" +
					OverlayProjection.observation.baseRevision.hex + "\u0000worktree\u0000" +
					occurrence.path,
			))
			{
				path: occurrence.path
				if occurrence.status == "deleted" {
					status: "deleted"
					kind:   "tombstone"
				}
				if occurrence.status != "deleted" {
					status: "present"
					kind:   occurrence.kind
				}
				memberID:   computedMemberID
				evidenceID: OverlayProjection.collected.worktree.state.evidenceID
				if occurrence.size != _|_ {
					gitSizeBytes: occurrence.size
				}
			}
		}]
		_pathSet: {
			for occurrence in committed {"\(occurrence.path)": true}
			for occurrence in index {"\(occurrence.path)": true}
			for occurrence in worktree {"\(occurrence.path)": true}
		}
		allPaths: [for path, _ in _pathSet {path}]
	}
	OverlaySnapshot=snapshot:           OverlayProjection.graph
	OverlayEffectiveView=effectiveView: OverlayEffectivePathEvaluation.view

	_rootEvaluation:         {snapshot: OverlaySnapshot, effectiveView: OverlayEffectiveView}
	_step1:                  {snapshot: OverlaySnapshot}
	_step2:                  {snapshot: OverlaySnapshot}
	_step3:                  {snapshot: OverlaySnapshot}
	_step4:                  {snapshot: OverlaySnapshot}
	_step5:                  {snapshot: OverlaySnapshot}
	_step6:                  {snapshot: OverlaySnapshot}
	_step7:                  {snapshot: OverlaySnapshot}
	_step8:                  {snapshot: OverlaySnapshot}
	_depthCompletion:        {snapshot: OverlaySnapshot}
	_effectiveFileSelection: {effectiveView: OverlayEffectiveView}
	_digestEvaluation:       {effectivePathView: OverlayEffectiveView}
})

#ContextGraphFailure: close({
	schema:    "dotfiles.context-graph-failure.v0"
	requestID: #ID
	stage:     "revision" | "manifest" | "hydration" | "snapshot" | "proposal" | "selection" | "packet"
	code:      #GraphID
	message:   #NonEmptyString
	details: [string]: _
})

#ContextGraphServiceSuccess: close({
	schema:     "dotfiles.context-graph-service-result.v0"
	status:     "success"
	evaluation: #ContextCommittedSelectionEvaluation | #ContextOverlaySelectionEvaluation
})

#ContextGraphServiceFailure: close({
	schema:  "dotfiles.context-graph-service-result.v0"
	status:  "failure"
	failure: #ContextGraphFailure
})

#ContextGraphServiceResult: #ContextGraphServiceSuccess | #ContextGraphServiceFailure
