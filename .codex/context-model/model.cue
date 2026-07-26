package contextmodel

import "strings"

// Provisional root vocabulary for the dotfiles context-establishment workbook.
// This package is intentionally local and replaceable. It is not a generalized
// kernel and has no dependency on CUEstrap or kernel-spec runtime artifacts.

#NonEmptyString: string & !=""
#ID:             #NonEmptyString & =~"^[a-z0-9]+([._-][a-z0-9]+)*$"
#Path:           #NonEmptyString & !~"(^|/)\\.\\.(/|$)" & !~"^/"
#Digest:         #NonEmptyString & =~"^sha256:[0-9a-f]{64}$"
#Confidence:     number & >=0 & <=1
#NonEmptyIDs:    [...#ID] & [_, ...]

#ArtifactClass:  "source" | "generated_projection" | "runtime_observation"
#SemanticRole:   "authority" | "constraint" | "workflow" | "evidence"
#ClaimAuthority: "none" | "candidate" | "controller" | "root"

#SourceLocator: {
	path:      #Path
	revision?: #NonEmptyString
	digest?:   #Digest
}

#AuthorityBinding: {
	semanticRole:   #SemanticRole
	artifactClass:  #ArtifactClass
	claimAuthority: #ClaimAuthority
	sourceRef?:     #SourceLocator

	if artifactClass != "source" {
		claimAuthority: "none" | "candidate"
	}
	if semanticRole == "evidence" {
		claimAuthority: "none" | "candidate"
	}
}

#RepositoryCoordinate: {
	repository:  #NonEmptyString
	root:        #Path | "."
	revision:    #NonEmptyString
	moduleRoot?: #Path | "."
}

#ContextRequest: {
	schema:                 "dotfiles.context-request.v0"
	requestID:              #ID
	prompt:                 #NonEmptyString
	repository:             #RepositoryCoordinate
	allowedPaths:           [...#Path]
	requestedProjectionIDs: [...#ID]
}

#ObservationKind: "prompt" | "repository" | "git" | "file" | "provider" | "tool"

// Observations may carry backend-specific facts, but never claimant verdicts.
#ObservationFacts: {
	[string]:    _
	pass?:       _|_
	passed?:     _|_
	success?:    _|_
	valid?:      _|_
	complete?:   _|_
	admitted?:   _|_
	aligned?:    _|_
	sufficient?: _|_
}

#SourceObservation: {
	kind:    #ObservationKind
	subject: #NonEmptyString
	facts:   #ObservationFacts
	diagnostics: [...{
		code:    #NonEmptyString
		message: #NonEmptyString
	}]
	provenance: #AuthorityBinding & {
		artifactClass:  "runtime_observation" | "source"
		claimAuthority: "none" | "candidate"
	}
}

#Evidence: {
	summary:        #NonEmptyString
	observationIDs: #NonEmptyIDs
	provenance: #AuthorityBinding & {
		semanticRole:   "evidence"
		claimAuthority: "none" | "candidate"
	}
}

#HypothesisState: "candidate" | "accepted" | "rejected" | "superseded"

#ContextHypothesis: {
	kind:        #ID
	statement:   #NonEmptyString
	state:       #HypothesisState
	evidenceIDs: #NonEmptyIDs
	confidence:  #Confidence
	derivedBy:   #ID
}

#ContextFragment: {
	summary:       #NonEmptyString
	sourceRef:     #SourceLocator
	prerequisites: [...#ID]
	authority:     #AuthorityBinding
}

#ProviderKind: "lsp" | "mcp" | "types" | "tool" | "repository"

#Provider: {
	kind:         #ProviderKind
	languages:    [...#ID]
	pathGlobs:    [...#NonEmptyString]
	evidenceOnly: true
	authority: #AuthorityBinding & {
		semanticRole:   "evidence"
		claimAuthority: "none"
	}
}

#ProviderObservation: {
	providerID:    #ID
	observationID: #ID
	query:         #NonEmptyString
	bounded:       true
}

#Workflow: {
	summary: #NonEmptyString
	steps: [...{
		id:        #ID
		dependsOn: [...#ID]
	}]
	authority: #AuthorityBinding
}

#ContextInventory: {
	fragments: [#ID]: #ContextFragment
	providers: [#ID]: #Provider
	workflows: [#ID]: #Workflow
}

#SelectionReason: {
	...
	reason:      #NonEmptyString
	evidenceIDs: #NonEmptyIDs
}

#FragmentSelection: #SelectionReason & {
	fragmentID: #ID
}

#FileSelection: #SelectionReason & {
	path: #Path
}

#ProviderSelection: #SelectionReason & {
	providerID: #ID
}

#WorkflowSelection: #SelectionReason & {
	workflowID: #ID
}

#ContextGap: {
	kind:                #ID
	description:         #NonEmptyString
	blocksSufficiency:   bool
	requiredEvidenceIDs: [...#ID]
}

#ConflictResolution: "unresolved" | "prefer_left" | "prefer_right" | "superseded" | "merged"

#ContextConflict: {
	leftRef:     #ID
	rightRef:    #ID
	description: #NonEmptyString
	evidenceIDs: #NonEmptyIDs
	resolution:  #ConflictResolution
}

#SufficiencyState: "insufficient" | "provisional" | "sufficient"

// These summary IDs are bound to the complete gap and conflict maps by
// #ContextState. They are never independently authoritative.
#ContextSufficiency: {
	state:                 #SufficiencyState
	reasons:               [...#NonEmptyString] & [_, ...]
	blockingGapIDs:        [...#ID]
	unresolvedConflictIDs: [...#ID]
}

#ContextPacket: {
	schema:        "dotfiles.context-packet.v0"
	requestID:     #ID
	contextDigest: #Digest
	selected: {
		fragmentIDs: [...#ID]
		files:       [...#Path]
		providerIDs: [...#ID]
		workflowIDs: [...#ID]
	}
	evidenceIDs:      [...#ID]
	unresolvedGapIDs: [...#ID]
	provenance: #AuthorityBinding & {
		artifactClass:  "generated_projection"
		claimAuthority: "none" | "candidate"
	}
}

#PluginProjectionKind: "agent_context_resolver" | "code_intel"

#PluginProjection: {
	kind:         #PluginProjectionKind
	packageRoot:  #Path
	inputSchema:  "dotfiles.context-state.v0"
	outputSchema: #NonEmptyString
	browserless:  bool
	authority: #AuthorityBinding & {
		artifactClass:  "generated_projection"
		claimAuthority: "none"
	}
}

#ContextState: {
	schema:              "dotfiles.context-state.v0"
	Request=request:     #ContextRequest
	Inventory=inventory: #ContextInventory
	Observations=observations: [#ID]: #SourceObservation
	providerObservations: [...#ProviderObservation]
	Evidence=evidence: [#ID]:     #Evidence
	Hypotheses=hypotheses: [#ID]: #ContextHypothesis
	Selected=selected: {
		fragments: [...#FragmentSelection]
		files:     [...#FileSelection]
		providers: [...#ProviderSelection]
		workflows: [...#WorkflowSelection]
	}
	Gaps=gaps: [#ID]:           #ContextGap
	Conflicts=conflicts: [#ID]: #ContextConflict

	// Concrete key inventories are required because CUE pattern fields are open:
	// indexing an unknown key would otherwise yield the value constraint instead
	// of bottom. Every reference below is checked against these materialized keys.
	_fragmentInventoryIDs: [for fragmentID, _ in Inventory.fragments {fragmentID}]
	_providerInventoryIDs: [for providerID, _ in Inventory.providers {providerID}]
	_workflowInventoryIDs: [for workflowID, _ in Inventory.workflows {workflowID}]
	_observationIDs:       [for observationID, _ in Observations {observationID}]
	_evidenceIDs:          [for evidenceID, _ in Evidence {evidenceID}]
	_gapIDs:               [for gapID, _ in Gaps {gapID}]

	// Derive the complete blocking and unresolved sets from their maps. The
	// sufficiency summary must unify with these exact derived lists.
	_blockingGapIDs:        [for gapID, gap in Gaps if gap.blocksSufficiency {gapID}]
	_unresolvedConflictIDs: [for conflictID, conflict in Conflicts if conflict.resolution == "unresolved" {conflictID}]
	sufficiency: #ContextSufficiency & {
		blockingGapIDs:        _blockingGapIDs
		unresolvedConflictIDs: _unresolvedConflictIDs
	}
	if sufficiency.state == "sufficient" {
		_blockingGapIDs:        []
		_unresolvedConflictIDs: []
	}

	projection?: #ContextPacket & {
		requestID: Request.requestID
		PacketSelected=selected: {
			fragmentIDs: [...#ID]
			files:       [...#Path]
			providerIDs: [...#ID]
			workflowIDs: [...#ID]
		}
		PacketEvidenceIDs=evidenceIDs: [...#ID]
		PacketGapIDs=unresolvedGapIDs: [...#ID]

		// A projected selection must already be selected in the context state.
		_selectedFragmentRefs: [for fragmentID in PacketSelected.fragmentIDs {
			selection: [for item in Selected.fragments if item.fragmentID == fragmentID {item}] & [_, ...]
			inventory: [for knownID in _fragmentInventoryIDs if knownID == fragmentID {knownID}] & [_, ...]
		}]
		_selectedFileRefs: [for path in PacketSelected.files {
			selection: [for item in Selected.files if item.path == path {item}] & [_, ...]
			allowed:   [for allowedPath in Request.allowedPaths if allowedPath == "." || path == allowedPath || strings.HasPrefix(path, allowedPath + "/") {allowedPath}] & [_, ...]
		}]
		_selectedProviderRefs: [for providerID in PacketSelected.providerIDs {
			selection: [for item in Selected.providers if item.providerID == providerID {item}] & [_, ...]
			inventory: [for knownID in _providerInventoryIDs if knownID == providerID {knownID}] & [_, ...]
		}]
		_selectedWorkflowRefs: [for workflowID in PacketSelected.workflowIDs {
			selection: [for item in Selected.workflows if item.workflowID == workflowID {item}] & [_, ...]
			inventory: [for knownID in _workflowInventoryIDs if knownID == workflowID {knownID}] & [_, ...]
		}]
		_evidenceRefs: [for evidenceID in PacketEvidenceIDs {
			[for knownID in _evidenceIDs if knownID == evidenceID {knownID}] & [_, ...]
		}]
		_unresolvedGapRefs: [for gapID in PacketGapIDs {
			[for knownID in _gapIDs if knownID == gapID {knownID}] & [_, ...]
		}]
	}

	// Referential-integrity checks are derived values, not transport fields.
	_selectedFragments: [for selection in Selected.fragments {
		[for knownID in _fragmentInventoryIDs if knownID == selection.fragmentID {knownID}] & [_, ...]
	}]
	_fragmentPrerequisiteRefs: [for _, fragment in Inventory.fragments {
		for prerequisiteID in fragment.prerequisites {
			[for knownID in _fragmentInventoryIDs if knownID == prerequisiteID {knownID}] & [_, ...]
		}
	}]
	_selectedFragmentPrerequisites: [for selection in Selected.fragments {
		for fragmentID, fragment in Inventory.fragments if fragmentID == selection.fragmentID {
			for prerequisiteID in fragment.prerequisites {
				[for selected in Selected.fragments if selected.fragmentID == prerequisiteID {selected}] & [_, ...]
			}
		}
	}]
	_selectedProviders: [for selection in Selected.providers {
		[for knownID in _providerInventoryIDs if knownID == selection.providerID {knownID}] & [_, ...]
	}]
	_selectedWorkflows: [for selection in Selected.workflows {
		[for knownID in _workflowInventoryIDs if knownID == selection.workflowID {knownID}] & [_, ...]
	}]
	_selectedFileBoundaries: [for selection in Selected.files {
		[for allowedPath in Request.allowedPaths if allowedPath == "." || selection.path == allowedPath || strings.HasPrefix(selection.path, allowedPath + "/") {allowedPath}] & [_, ...]
	}]
	_providerObservationRefs: [for item in providerObservations {
		provider:    [for knownID in _providerInventoryIDs if knownID == item.providerID {knownID}] & [_, ...]
		observation: [for knownID in _observationIDs if knownID == item.observationID {knownID}] & [_, ...]
	}]
	_evidenceObservationRefs: [for _, item in Evidence {
		for observationID in item.observationIDs {
			[for knownID in _observationIDs if knownID == observationID {knownID}] & [_, ...]
		}
	}]
	_hypothesisEvidenceRefs: [for _, item in Hypotheses {
		for evidenceID in item.evidenceIDs {
			[for knownID in _evidenceIDs if knownID == evidenceID {knownID}] & [_, ...]
		}
	}]
	_selectionEvidenceRefs: [
		for selection in Selected.fragments {
			for evidenceID in selection.evidenceIDs {[for knownID in _evidenceIDs if knownID == evidenceID {knownID}] & [_, ...]}
		},
		for selection in Selected.files {
			for evidenceID in selection.evidenceIDs {[for knownID in _evidenceIDs if knownID == evidenceID {knownID}] & [_, ...]}
		},
		for selection in Selected.providers {
			for evidenceID in selection.evidenceIDs {[for knownID in _evidenceIDs if knownID == evidenceID {knownID}] & [_, ...]}
		},
		for selection in Selected.workflows {
			for evidenceID in selection.evidenceIDs {[for knownID in _evidenceIDs if knownID == evidenceID {knownID}] & [_, ...]}
		},
	]
	_conflictEvidenceRefs: [for _, item in Conflicts {
		for evidenceID in item.evidenceIDs {
			[for knownID in _evidenceIDs if knownID == evidenceID {knownID}] & [_, ...]
		}
	}]
}

#MigrationBoundary: {
	status:                    "provisional"
	externalRuntimeDependency: false
	target:                    "unresolved"
	replacementRequires:       [...#ID] & [_, ...]
}

#ContextModel: {
	schema:    "dotfiles.context-model.v0"
	status:    "provisional"
	scope:     "dotfiles_codex_plugins"
	migration: #MigrationBoundary
	inventory: #ContextInventory
	projections: [#ID]: #PluginProjection
}
