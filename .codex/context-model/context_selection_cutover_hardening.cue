package contextmodel

import (
	"list"
	"strings"
)

// Canonicality is enforced at the complete application boundary rather than on
// the transport definitions themselves. This keeps malformed mutation fixtures
// representable until a property runner explicitly evaluates them.
#ContextSelectionCanonicalSurface: {
	Proposal=proposal:       #ContextRootProposal
	RootCatalog=rootCatalog: #ContextRootCatalog
	Proof=proof:             #ContextSelectionProof
	Aliases=aliases:         [...#ContextPacketEvidenceAlias]

	_proposalMemberIDsSorted:    list.IsSortedStrings(Proposal.memberIDs) & true
	_proposalMemberIDsUnique:    list.UniqueItems(Proposal.memberIDs) & true
	_proposalNamespaceIDsSorted: list.IsSortedStrings(Proposal.namespaceIDs) & true
	_proposalNamespaceIDsUnique: list.UniqueItems(Proposal.namespaceIDs) & true
	_proposalPathPrefixesSorted: list.IsSortedStrings(Proposal.pathPrefixes) & true
	_proposalPathPrefixesUnique: list.UniqueItems(Proposal.pathPrefixes) & true
	_catalogMemberIDsSorted:     list.IsSortedStrings(RootCatalog.memberIDs) & true
	_catalogMemberIDsUnique:     list.UniqueItems(RootCatalog.memberIDs) & true
	_catalogNamespaceIDsSorted:  list.IsSortedStrings(RootCatalog.namespaceIDs) & true
	_catalogNamespaceIDsUnique:  list.UniqueItems(RootCatalog.namespaceIDs) & true
	_catalogPathsSorted:         list.IsSortedStrings(RootCatalog.paths) & true
	_catalogPathsUnique:         list.UniqueItems(RootCatalog.paths) & true
	_relationshipsSorted:        list.IsSortedStrings(Proof.relationshipIDs) & true
	_relationshipsUnique:        list.UniqueItems(Proof.relationshipIDs) & true
	_evidenceSorted:             list.IsSortedStrings(Proof.evidenceIDs) & true
	_evidenceUnique:             list.UniqueItems(Proof.evidenceIDs) & true
	_effectiveFilesSorted:       list.IsSortedStrings(Proof.effectiveFiles) & true
	_effectiveFilesUnique:       list.UniqueItems(Proof.effectiveFiles) & true
	_selectedKeys:               [for entity in Proof.selected {entity.kind + "\u0000" + entity.id}]
	_selectedUnique:             list.UniqueItems(_selectedKeys) & true
	_aliasGraphEvidenceIDs:      [for alias in Aliases {alias.graphEvidenceID}]
	_aliasPacketEvidenceIDs:     [for alias in Aliases {alias.packetEvidenceID}]
	_aliasGraphSorted:           list.IsSortedStrings(_aliasGraphEvidenceIDs) & true
	_aliasGraphUnique:           list.UniqueItems(_aliasGraphEvidenceIDs) & true
	_aliasPacketSorted:          list.IsSortedStrings(_aliasPacketEvidenceIDs) & true
	_aliasPacketUnique:          list.UniqueItems(_aliasPacketEvidenceIDs) & true
	_frontiers:                  [Proof.frontier0, Proof.frontier1, Proof.frontier2, Proof.frontier3, Proof.frontier4, Proof.frontier5, Proof.frontier6, Proof.frontier7, Proof.frontier8]
	_frontierCanonicality: [for frontier in _frontiers {
		let entityKeys = [for record in frontier.entities {
			record.entity.kind + "\u0000" + record.entity.id
		}]
		sorted: list.IsSortedStrings(entityKeys) & true
		unique: list.UniqueItems(entityKeys) & true
	}]
}

// Structural containment ancestry is permitted, but no path-bearing selected
// member or packet file may escape the request's allowed path boundary.
#ContextSelectionRequestBoundary: {
	Request=request:      #ContextApplicationRequest
	Snapshot=snapshot:    #ContextGraphSnapshot
	Selected=selected:    [...#ContextEntityRef]
	EffectiveFiles=files: [...#Path]

	_selectedMembersBounded: [for selectedEntity in Selected
	if selectedEntity.kind == "member" {
		let selectedMember = Snapshot.members[selectedEntity.id]
		if selectedMember.path != _|_ {
			[for allowed in Request.allowedPaths
			if allowed == "." || selectedMember.path == allowed ||
				strings.HasPrefix(selectedMember.path, allowed + "/") {
				allowed
			}] & [_, ...]
		}
	}]
	_effectiveFilesBounded: [for selectedPath in EffectiveFiles {
		[for allowed in Request.allowedPaths
		if allowed == "." || selectedPath == allowed ||
			strings.HasPrefix(selectedPath, allowed + "/") {
			allowed
		}] & [_, ...]
	}]
}

#ContextSelectionEvaluation: {
	CutoverRequest=request:             #ContextApplicationRequest
	CutoverSnapshot=snapshot:           #ContextGraphSnapshot
	CutoverProposal=proposal:           #ContextRootProposal
	CutoverPolicy=policy:               #ContextSelectionPolicy
	CutoverEffectiveView=effectiveView: #GitEffectivePathView
	CutoverRootCatalog=rootCatalog:     #ContextRootCatalog
	CutoverProof=proof:                 #ContextSelectionProof
	CutoverPacket=packet:               #ContextPacketV0Projection

	_rootEvaluation: {
		request:       CutoverRequest
		proposal:      CutoverProposal
		policy:        CutoverPolicy
		snapshot:      CutoverSnapshot
		effectiveView: CutoverEffectiveView
	}
	_step1:                  {snapshot: CutoverSnapshot, predicates: CutoverPolicy.predicates}
	_step2:                  {snapshot: CutoverSnapshot, predicates: CutoverPolicy.predicates}
	_step3:                  {snapshot: CutoverSnapshot, predicates: CutoverPolicy.predicates}
	_step4:                  {snapshot: CutoverSnapshot, predicates: CutoverPolicy.predicates}
	_step5:                  {snapshot: CutoverSnapshot, predicates: CutoverPolicy.predicates}
	_step6:                  {snapshot: CutoverSnapshot, predicates: CutoverPolicy.predicates}
	_step7:                  {snapshot: CutoverSnapshot, predicates: CutoverPolicy.predicates}
	_step8:                  {snapshot: CutoverSnapshot, predicates: CutoverPolicy.predicates}
	_depthCompletion:        {snapshot: CutoverSnapshot, predicates: CutoverPolicy.predicates}
	_effectiveFileSelection: {effectiveView: CutoverEffectiveView}
	_digestEvaluation: {
		request:           CutoverRequest, proposal:          CutoverProposal, policy:            CutoverPolicy, effectivePathView: CutoverEffectiveView
	}

	_cutoverCanonicalSurface: #ContextSelectionCanonicalSurface & {
		proposal:    CutoverProposal, rootCatalog: CutoverRootCatalog, proof:       CutoverProof, aliases:     CutoverPacket.aliases
	}
	_cutoverRequestBoundary: #ContextSelectionRequestBoundary & {
		request:  CutoverRequest, snapshot: CutoverSnapshot, selected: CutoverProof.selected, files:    CutoverProof.effectiveFiles
	}
}

// Bind internal evaluators after each subtype has supplied its concrete
// projection graph. References declared only in the common definition retain
// the generic graph and cannot make traversal records concrete under CUE's
// lexical reference rules.
#ContextCommittedSelectionEvaluation: {
	CommittedRequest=request:             #ContextApplicationRequest
	CommittedProposal=proposal:           #ContextRootProposal
	CommittedPolicy=policy:               #ContextSelectionPolicy
	CommittedSnapshot=snapshot:           #ContextGraphSnapshot
	CommittedEffectiveView=effectiveView: #GitEffectivePathView

	_rootEvaluation: {
		request:       CommittedRequest
		proposal:      CommittedProposal
		policy:        CommittedPolicy
		snapshot:      CommittedSnapshot
		effectiveView: CommittedEffectiveView
	}
	_step1:                  {snapshot: CommittedSnapshot, predicates: CommittedPolicy.predicates}
	_step2:                  {snapshot: CommittedSnapshot, predicates: CommittedPolicy.predicates}
	_step3:                  {snapshot: CommittedSnapshot, predicates: CommittedPolicy.predicates}
	_step4:                  {snapshot: CommittedSnapshot, predicates: CommittedPolicy.predicates}
	_step5:                  {snapshot: CommittedSnapshot, predicates: CommittedPolicy.predicates}
	_step6:                  {snapshot: CommittedSnapshot, predicates: CommittedPolicy.predicates}
	_step7:                  {snapshot: CommittedSnapshot, predicates: CommittedPolicy.predicates}
	_step8:                  {snapshot: CommittedSnapshot, predicates: CommittedPolicy.predicates}
	_depthCompletion:        {snapshot: CommittedSnapshot, predicates: CommittedPolicy.predicates}
	_effectiveFileSelection: {effectiveView: CommittedEffectiveView}
	_digestEvaluation: {
		request:           CommittedRequest, proposal:          CommittedProposal, policy:            CommittedPolicy, effectivePathView: CommittedEffectiveView
	}
}

#ContextOverlaySelectionEvaluation: {
	OverlayRequest=request:             #ContextApplicationRequest
	OverlayProposal=proposal:           #ContextRootProposal
	OverlayPolicy=policy:               #ContextSelectionPolicy
	OverlaySnapshot=snapshot:           #ContextGraphSnapshot
	OverlayEffectiveView=effectiveView: #GitEffectivePathView

	_rootEvaluation: {
		request:       OverlayRequest
		proposal:      OverlayProposal
		policy:        OverlayPolicy
		snapshot:      OverlaySnapshot
		effectiveView: OverlayEffectiveView
	}
	_step1:                  {snapshot: OverlaySnapshot, predicates: OverlayPolicy.predicates}
	_step2:                  {snapshot: OverlaySnapshot, predicates: OverlayPolicy.predicates}
	_step3:                  {snapshot: OverlaySnapshot, predicates: OverlayPolicy.predicates}
	_step4:                  {snapshot: OverlaySnapshot, predicates: OverlayPolicy.predicates}
	_step5:                  {snapshot: OverlaySnapshot, predicates: OverlayPolicy.predicates}
	_step6:                  {snapshot: OverlaySnapshot, predicates: OverlayPolicy.predicates}
	_step7:                  {snapshot: OverlaySnapshot, predicates: OverlayPolicy.predicates}
	_step8:                  {snapshot: OverlaySnapshot, predicates: OverlayPolicy.predicates}
	_depthCompletion:        {snapshot: OverlaySnapshot, predicates: OverlayPolicy.predicates}
	_effectiveFileSelection: {effectiveView: OverlayEffectiveView}
	_digestEvaluation: {
		request:           OverlayRequest, proposal:          OverlayProposal, policy:            OverlayPolicy, effectivePathView: OverlayEffectiveView
	}
}
