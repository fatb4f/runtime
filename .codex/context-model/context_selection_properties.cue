package contextmodel

import "list"

#ContextSelectionPropertyID:
	"relationship-predecessor-binds-edge" |
		"contains-ancestry-is-bidirectional" |
		"depth-eight-is-terminal" |
		"submitted-root-specifications-are-bounded" |
		"forensic-roots-preserve-layer-occurrences" |
		"context-digest-binds-canonical-envelope"

contextSelectionProperties: close({
	"relationship-predecessor-binds-edge":       true
	"contains-ancestry-is-bidirectional":        true
	"depth-eight-is-terminal":                   true
	"submitted-root-specifications-are-bounded": true
	"forensic-roots-preserve-layer-occurrences": true
	"context-digest-binds-canonical-envelope":   true
})

#ContextSelectionMutationKind:
	"competing-incoming-and-outgoing-proof" |
		"reverse-contains-root" |
		"ninth-hop-or-back-edge" |
		"root-submission-count-change" |
		"effective-layer-change" |
		"canonical-envelope-component-change"

#ContextSelectionInvariantTerm:
	"relationship-proof-identity" |
		"traversal-direction" |
		"contains-connectivity" |
		"visited-entity-set" |
		"depth-bound" |
		"raw-root-count" |
		"prefix-expansion" |
		"forensic-member-catalog" |
		"effective-path-winner" |
		"effective-file-projection" |
		"adapter-version" |
		"context-digest" |
		"canonical-input"

#ContextSelectionStrategyCoverage: close({
	positive:    [#GraphID, ...#GraphID]
	negative:    [#GraphID, ...#GraphID]
	boundary:    [#GraphID, ...#GraphID]
	metamorphic: [#GraphID, ...#GraphID]
})

#ContextSelectionProperty: close({
	id:            #ContextSelectionPropertyID
	description:   #NonEmptyString
	mutation:      #ContextSelectionMutationKind
	preconditions: [...#GraphID]
	preserves:     [...#ContextSelectionInvariantTerm]
	changes:       [...#ContextSelectionInvariantTerm]
	expected:      "accept" | "reject-mutation"
	strategies:    #ContextSelectionStrategyCoverage
})

#ContextSelectionPropertyCatalog: close({
	schema: "kernel.context-selection-properties.v0"
	properties: [ID=#ContextSelectionPropertyID]: #ContextSelectionProperty & {
		id: ID
	}
})

contextSelectionPropertyCatalog: #ContextSelectionPropertyCatalog & {
	properties: {
		"relationship-predecessor-binds-edge": {
			description:   "A traversal record names the lexicographically lowest qualifying relationship and derives direction from that edge."
			mutation:      "competing-incoming-and-outgoing-proof"
			preconditions: ["same-candidate", "multiple-contains-proofs"]
			preserves:     ["relationship-proof-identity", "visited-entity-set"]
			changes:       ["traversal-direction"]
			expected:      "accept"
			strategies: {
				positive:    ["outgoing-proof"]
				negative:    ["entity-id-predecessor"]
				boundary:    ["lowest-incoming-proof"]
				metamorphic: ["relationship-order-perturbation"]
			}
		}
		"contains-ancestry-is-bidirectional": {
			description:   "Policy-approved contains relationships traverse from parent to child and from child to parent."
			mutation:      "reverse-contains-root"
			preconditions: ["contains-edge", "child-root"]
			preserves:     ["contains-connectivity", "visited-entity-set"]
			changes:       ["traversal-direction"]
			expected:      "accept"
			strategies: {
				positive:    ["parent-to-child"]
				negative:    ["non-contains-edge"]
				boundary:    ["child-to-parent"]
				metamorphic: ["root-endpoint-reversal"]
			}
		}
		"depth-eight-is-terminal": {
			description:   "Depth eight accepts terminal graphs and visited back-edges but rejects any reachable unvisited entity."
			mutation:      "ninth-hop-or-back-edge"
			preconditions: ["eight-frontiers", "contains-policy"]
			preserves:     ["depth-bound", "visited-entity-set"]
			changes:       []
			expected:      "reject-mutation"
			strategies: {
				positive:    ["depth-eight-terminal"]
				negative:    ["reachable-ninth-entity"]
				boundary:    ["depth-eight-back-edge"]
				metamorphic: ["visited-cycle-insertion"]
			}
		}
		"submitted-root-specifications-are-bounded": {
			description:   "The root limit counts raw request and proposal entries before deduplication or prefix expansion."
			mutation:      "root-submission-count-change"
			preconditions: ["catalogued-roots", "valid-policy"]
			preserves:     ["raw-root-count", "prefix-expansion"]
			changes:       []
			expected:      "reject-mutation"
			strategies: {
				positive:    ["sixty-four-submissions"]
				negative:    ["sixty-five-submissions"]
				boundary:    ["one-prefix-sixty-five-seeds"]
				metamorphic: ["cross-source-duplicate"]
			}
		}
		"forensic-roots-preserve-layer-occurrences": {
			description:   "Exact roots admit every path-bearing layer occurrence while prefix and effective-file projection use only present winners."
			mutation:      "effective-layer-change"
			preconditions: ["same-path-layer-occurrences", "effective-view"]
			preserves:     ["forensic-member-catalog", "effective-path-winner"]
			changes:       ["effective-file-projection"]
			expected:      "accept"
			strategies: {
				positive:    ["superseded-exact-root"]
				negative:    ["tombstone-prefix-expansion"]
				boundary:    ["tombstone-exact-root"]
				metamorphic: ["effective-winner-substitution"]
			}
		}
		"context-digest-binds-canonical-envelope": {
			description:   "The versioned digest envelope binds every authoritative input and projection component deterministically."
			mutation:      "canonical-envelope-component-change"
			preconditions: ["canonical-input", "fixed-adapter-version"]
			preserves:     ["adapter-version", "canonical-input"]
			changes:       ["context-digest"]
			expected:      "accept"
			strategies: {
				positive:    ["identical-input"]
				negative:    ["unbound-component"]
				boundary:    ["empty-projection-lists"]
				metamorphic: ["each-envelope-component"]
			}
		}
	}
}

_contextSelectionCatalogCoversManifest: {
	for ID, _ in contextSelectionProperties {
		"\(ID)": contextSelectionPropertyCatalog.properties[ID]
	}
}
_contextSelectionManifestCoversCatalog: {
	for ID, _ in contextSelectionPropertyCatalog.properties {
		"\(ID)": contextSelectionProperties[ID]
	}
}

#ContextSelectionQualificationReport: close({
	schema: "kernel.context-selection-qualification-report.v0"

	Declared=declaredPropertyIDs: [...#ContextSelectionPropertyID]
	generatedPropertyIDs:         Declared
	executedPropertyIDs:          Declared
	reportedPropertyIDs:          Declared

	propertyReport: close({
		schema: "kernel.context-selection-property-report.v0"
		results: [...close({
			propertyID: #ContextSelectionPropertyID
			status:     "passed"
		})]
		_resultIDs: [for result in results {result.propertyID}]
		_unique:    list.UniqueItems(_resultIDs) & true
	})
})

#SelectionPropertyPolicy: #ContextSelectionPolicy & {
	schema:     "dotfiles.context-selection-policy.v0"
	predicates: ["contains"]
	limits: {
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
	}
}

#SelectionPropertyMember: #ContextMember & {
	moduleID:    "module.fixture"
	namespaceID: "namespace.fixture"
	name:        "fixture"
	kind:        "file"
}

#SelectionPropertySnapshot: #ContextGraphSnapshot & {
	schema:     "kernel.context-graph.v0"
	snapshotID: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	modules: {
		"module.fixture": {
			kind:            "repository"
			name:            "fixture"
			rootNamespaceID: "namespace.fixture"
		}
	}
	namespaces: {
		"namespace.fixture": {
			moduleID:          "module.fixture"
			parentNamespaceID: null
			name:              "fixture"
			kind:              "repository-root"
			rootPath:          "."
		}
	}
	evidence: {}
	provenance: {
		authorityDigest: "sha256:1111111111111111111111111111111111111111111111111111111111111111"
		schemaDigest:    "sha256:2222222222222222222222222222222222222222222222222222222222222222"
		hydratorDigest:  "sha256:3333333333333333333333333333333333333333333333333333333333333333"
	}
}

#SelectionPropertyRootRequest: #ContextApplicationRequest & {
	schema:       "dotfiles.context-application-request.v0"
	requestID:    "request.selection-property"
	repository:   "fixture"
	revision:     "HEAD"
	allowedPaths: ["src"]
	overlayMode:  "auto"
}

#SelectionPropertyProposal: #ContextRootProposal & {
	schema:     "dotfiles.context-root-proposal.v0"
	requestID:  "request.selection-property"
	snapshotID: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}

#SelectionPropertyRootSnapshot: #SelectionPropertySnapshot & {
	members: {
		"member.root": #SelectionPropertyMember & {
			path: "src/root"
		}
	}
	relationships: {}
}

#SelectionPropertyRootView: #GitEffectivePathView & {
	schema:     "dotfiles.git-effective-path-view.v0"
	snapshotID: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	paths: [{
		path:         "src/root"
		layer:        "committed"
		status:       "present"
		kind:         "blob"
		memberID:     "member.root"
		evidenceID:   "evidence.root"
		gitSizeBytes: 1
	}]
}

#SelectionRootCountCase: {
	RequestCount=requestCount:   int & >=1
	ProposalCount=proposalCount: int & >=0
	request: #SelectionPropertyRootRequest & {
		roots: {
			memberIDs:    [for _ in list.Range(0, RequestCount, 1) {"member.root"}]
			namespaceIDs: []
			pathPrefixes: []
		}
	}
	proposal: #SelectionPropertyProposal & {
		memberIDs:    [for _ in list.Range(0, ProposalCount, 1) {"member.root"}]
		namespaceIDs: []
		pathPrefixes: []
	}
	policy:        #SelectionPropertyPolicy
	snapshot:      #SelectionPropertyRootSnapshot
	effectiveView: #SelectionPropertyRootView
}

#SelectionForensicCase: {
	Mode=mode: "exact" | "prefix"
	request: #SelectionPropertyRootRequest & {
		if Mode == "exact" {
			roots: {
				memberIDs:    ["member.tombstone"]
				namespaceIDs: []
				pathPrefixes: []
			}
		}
		if Mode == "prefix" {
			roots: {
				memberIDs:    []
				namespaceIDs: []
				pathPrefixes: ["src"]
			}
		}
	}
	proposal: #SelectionPropertyProposal & {
		if Mode == "exact" {
			memberIDs: ["member.superseded"]
		}
		if Mode == "prefix" {
			memberIDs: []
		}
		namespaceIDs: []
		pathPrefixes: []
	}
	policy: #SelectionPropertyPolicy
	snapshot: #SelectionPropertySnapshot & {
		members: {
			"member.effective": #SelectionPropertyMember & {
				path: "src/item"
			}
			"member.superseded": #SelectionPropertyMember & {
				path: "src/item"
				properties: {
					overlayLayer:  "index"
					overlayStatus: "modified"
				}
			}
			"member.tombstone": #SelectionPropertyMember & {
				path: "src/item"
				properties: {
					overlayLayer:  "worktree"
					overlayStatus: "deleted"
				}
			}
		}
		relationships: {}
	}
	effectiveView: #GitEffectivePathView & {
		schema:     "dotfiles.git-effective-path-view.v0"
		snapshotID: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
		paths: [{
			path:         "src/item"
			layer:        "committed"
			status:       "present"
			kind:         "blob"
			memberID:     "member.effective"
			evidenceID:   "evidence.effective"
			gitSizeBytes: 1
		}]
	}
}

#SelectionDigestCase: {
	Variant=variant:
		"base" |
			"request" |
			"proposal" |
			"policy" |
			"effective-view" |
			"traversal" |
			"selected" |
			"relationships" |
			"evidence" |
			"files" |
			"aliases"

	adapterVersion: "context-packet-v0-adapter.v1"
	request: #ContextApplicationRequest & {
		schema:       "dotfiles.context-application-request.v0"
		requestID:    "request.digest"
		repository:   "fixture"
		overlayMode:  "auto"
		allowedPaths: ["src"]
		roots: {
			memberIDs:    ["member.root"]
			namespaceIDs: []
			pathPrefixes: []
		}
		if Variant == "request" {
			revision: "CHANGED"
		}
		if Variant != "request" {
			revision: "HEAD"
		}
	}
	proposal: #ContextRootProposal & {
		schema:       "dotfiles.context-root-proposal.v0"
		requestID:    "request.digest"
		snapshotID:   "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
		namespaceIDs: []
		pathPrefixes: []
		if Variant == "proposal" {
			memberIDs: ["member.proposal"]
		}
		if Variant != "proposal" {
			memberIDs: []
		}
	}
	policy: #ContextSelectionPolicy & {
		schema: "dotfiles.context-selection-policy.v0"
		if Variant == "policy" {
			predicates: []
		}
		if Variant != "policy" {
			predicates: ["contains"]
		}
		limits: {
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
		}
	}
	effectivePathView: #GitEffectivePathView & {
		schema:     "dotfiles.git-effective-path-view.v0"
		snapshotID: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
		paths: [{
			path:       "src/root"
			layer:      "committed"
			kind:       "blob"
			memberID:   "member.root"
			evidenceID: "evidence.root"
			if Variant == "effective-view" {
				status: "deleted"
			}
			if Variant != "effective-view" {
				status:       "present"
				gitSizeBytes: 1
			}
		}]
	}
	if Variant == "traversal" {
		traversalRecords: [{
			entity:      {kind: "member", id: "member.root"}
			distance:    0
			direction:   "root"
			predecessor: null
		}, {
			entity:      {kind: "member", id: "member.traversed"}
			distance:    1
			direction:   "outgoing"
			predecessor: "rel.traversed"
		}]
	}
	if Variant != "traversal" {
		traversalRecords: [{
			entity:      {kind: "member", id: "member.root"}
			distance:    0
			direction:   "root"
			predecessor: null
		}]
	}
	if Variant == "selected" {
		selectedEntities: [{kind: "member", id: "member.changed"}]
	}
	if Variant != "selected" {
		selectedEntities: [{kind: "member", id: "member.root"}]
	}
	if Variant == "relationships" {
		relationshipIDs: ["rel.changed"]
	}
	if Variant != "relationships" {
		relationshipIDs: []
	}
	if Variant == "evidence" {
		evidenceIDs: ["evidence.changed"]
	}
	if Variant != "evidence" {
		evidenceIDs: []
	}
	if Variant == "files" {
		effectiveFiles: ["src/changed"]
	}
	if Variant != "files" {
		effectiveFiles: ["src/root"]
	}
	if Variant == "aliases" {
		evidenceAliases: [{
			graphEvidenceID:  "evidence.changed"
			packetEvidenceID: "evidence." + "changed"
		}]
	}
	if Variant != "aliases" {
		evidenceAliases: []
	}
}

contextSelectionPropertyFixtures: {
	relationshipPredecessor: {
		snapshot: #SelectionPropertySnapshot & {
			members: {
				"member.root":   #SelectionPropertyMember & {path: "src/root"}
				"member.target": #SelectionPropertyMember & {path: "src/target"}
			}
			relationships: {
				"rel.a.in": {
					subject:     {kind: "member", id: "member.target"}
					predicate:   "contains"
					object:      {kind: "member", id: "member.root"}
					evidenceIDs: []
				}
				"rel.z.out": {
					subject:     {kind: "member", id: "member.root"}
					predicate:   "contains"
					object:      {kind: "member", id: "member.target"}
					evidenceIDs: []
				}
			}
		}
		predicates: ["contains"]
		previous: [{
			entity:      {kind: "member", id: "member.root"}
			distance:    0
			direction:   "root"
			predecessor: null
		}]
		visited:  previous
		distance: 1
	}

	incomingAncestry: {
		snapshot: #SelectionPropertySnapshot & {
			members: {}
			relationships: {
				"rel.contains-root": {
					subject:     {kind: "module", id: "module.fixture"}
					predicate:   "contains"
					object:      {kind: "namespace", id: "namespace.fixture"}
					evidenceIDs: []
				}
			}
		}
		predicates: ["contains"]
		previous: [{
			entity:      {kind: "namespace", id: "namespace.fixture"}
			distance:    0
			direction:   "root"
			predecessor: null
		}]
		visited:  previous
		distance: 1
	}

	depth: {
		visited: [for index in list.Range(0, 9, 1) {
			entity:      {kind: "member", id: "member.node-\(index)"}
			distance:    index
			direction:   "root"
			predecessor: null
		}]
		terminal: {
			snapshot: #SelectionPropertySnapshot & {
				members: {
					for index in list.Range(0, 9, 1) {
						"member.node-\(index)": #SelectionPropertyMember & {
							path: "src/node-\(index)"
						}
					}
				}
				relationships: {
					for index in list.Range(0, 8, 1) {
						"rel.chain-\(index)": {
							subject:     {kind: "member", id: "member.node-\(index)"}
							predicate:   "contains"
							object:      {kind: "member", id: "member.node-\(index+1)"}
							evidenceIDs: []
						}
					}
				}
			}
			predicates: ["contains"]
			visited:    depth.visited
		}
		overflow: {
			snapshot: #SelectionPropertySnapshot & {
				members: {
					for index in list.Range(0, 10, 1) {
						"member.node-\(index)": #SelectionPropertyMember & {
							path: "src/node-\(index)"
						}
					}
				}
				relationships: {
					for index in list.Range(0, 9, 1) {
						"rel.chain-\(index)": {
							subject:     {kind: "member", id: "member.node-\(index)"}
							predicate:   "contains"
							object:      {kind: "member", id: "member.node-\(index+1)"}
							evidenceIDs: []
						}
					}
				}
			}
			predicates: ["contains"]
			visited:    depth.visited
		}
		backEdge: {
			snapshot: terminal.snapshot & {
				relationships: {
					"rel.back": {
						subject:     {kind: "member", id: "member.node-8"}
						predicate:   "contains"
						object:      {kind: "member", id: "member.node-0"}
						evidenceIDs: []
					}
				}
			}
			predicates: ["contains"]
			visited:    depth.visited
		}
	}

	rootCounting: {
		count64:              #SelectionRootCountCase & {requestCount: 64, proposalCount: 0}
		count65:              #SelectionRootCountCase & {requestCount: 65, proposalCount: 0}
		crossSourceDuplicate: #SelectionRootCountCase & {requestCount: 32, proposalCount: 33}
		prefixExpansion: {
			request: #SelectionPropertyRootRequest & {
				roots: {
					memberIDs:    []
					namespaceIDs: []
					pathPrefixes: ["src"]
				}
			}
			proposal: #SelectionPropertyProposal & {
				memberIDs:    []
				namespaceIDs: []
				pathPrefixes: []
			}
			policy: #SelectionPropertyPolicy
			snapshot: #SelectionPropertySnapshot & {
				members: {
					for index in list.Range(0, 65, 1) {
						"member.seed-\(index)": #SelectionPropertyMember & {
							path: "src/seed-\(index)"
						}
					}
				}
				relationships: {}
			}
			effectiveView: #GitEffectivePathView & {
				schema:     "dotfiles.git-effective-path-view.v0"
				snapshotID: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
				paths: [for index in list.Range(0, 65, 1) {
					path:         "src/seed-\(index)"
					layer:        "committed"
					status:       "present"
					kind:         "blob"
					memberID:     "member.seed-\(index)"
					evidenceID:   "evidence.seed"
					gitSizeBytes: 1
				}]
			}
		}
	}

	forensicRoots: {
		exact:  #SelectionForensicCase & {mode: "exact"}
		prefix: #SelectionForensicCase & {mode: "prefix"}
		effectiveFiles: {
			effectiveView: exact.effectiveView
			selected: [
				{kind: "member", id: "member.effective"},
				{kind: "member", id: "member.superseded"},
				{kind: "member", id: "member.tombstone"},
			]
		}
	}

	digest: {
		base:      #SelectionDigestCase & {variant: "base"}
		identical: #SelectionDigestCase & {variant: "base"}
		for variantValue in [
			"request",
			"proposal",
			"policy",
			"effective-view",
			"traversal",
			"selected",
			"relationships",
			"evidence",
			"files",
			"aliases",
		] {
			"\(variantValue)": #SelectionDigestCase & {variant: variantValue}
		}
	}
}
