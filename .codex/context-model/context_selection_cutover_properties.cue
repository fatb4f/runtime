package contextmodel

import "list"

#ContextSelectionCutoverPropertyID:
	"allowed-path-boundary-is-fail-closed" |
		"proposal-and-proof-order-is-canonical" |
		"committed-selection-evaluates-end-to-end"

contextSelectionCutoverProperties: close({
	"allowed-path-boundary-is-fail-closed":     true
	"proposal-and-proof-order-is-canonical":    true
	"committed-selection-evaluates-end-to-end": true
})

#ContextSelectionCutoverProperty: close({
	id:          #ContextSelectionCutoverPropertyID
	description: #NonEmptyString
	strategies: close({
		positive: [...#GraphID]
		negative: [...#GraphID]
		boundary: [...#GraphID]
	})
})

#ContextSelectionCutoverPropertyCatalog: close({
	schema: "kernel.context-selection-cutover-properties.v0"
	properties: [ID=#ContextSelectionCutoverPropertyID]: #ContextSelectionCutoverProperty & {id: ID}
})

contextSelectionCutoverPropertyCatalog: #ContextSelectionCutoverPropertyCatalog & {
	properties: {
		"allowed-path-boundary-is-fail-closed": {
			description: "Selected path-bearing members and packet files remain inside request.allowedPaths."
			strategies: {
				positive: ["inside-boundary"]
				negative: ["outside-member", "outside-file"]
				boundary: ["repository-root-boundary"]
			}
		}
		"proposal-and-proof-order-is-canonical": {
			description: "Root proposals, frontiers, relationship IDs, evidence IDs, files, and aliases are sorted and unique."
			strategies: {
				positive: ["canonical-order"]
				negative: ["unsorted-proposal", "duplicate-evidence"]
				boundary: ["empty-canonical-lists"]
			}
		}
		"committed-selection-evaluates-end-to-end": {
			description: "A committed observation projects, selects explicit roots, and emits a packet through the authoritative CUE evaluation."
			strategies: {
				positive: ["committed-success"]
				negative: ["committed-outside-boundary"]
				boundary: ["committed-single-file"]
			}
		}
	}
}

_contextSelectionCutoverCatalogCoversManifest: {
	for ID, _ in contextSelectionCutoverProperties {
		"\(ID)": contextSelectionCutoverPropertyCatalog.properties[ID]
	}
}
_contextSelectionCutoverManifestCoversCatalog: {
	for ID, _ in contextSelectionCutoverPropertyCatalog.properties {
		"\(ID)": contextSelectionCutoverProperties[ID]
	}
}

#ContextSelectionCutoverQualificationReport: close({
	schema:                       "kernel.context-selection-cutover-qualification-report.v0"
	Declared=declaredPropertyIDs: [...#ContextSelectionCutoverPropertyID]
	generatedPropertyIDs:         Declared
	executedPropertyIDs:          Declared
	reportedPropertyIDs:          Declared
	propertyReport: close({
		schema:     "kernel.context-selection-cutover-property-report.v0"
		results:    [...close({propertyID: #ContextSelectionCutoverPropertyID, status: "passed"})]
		_resultIDs: [for result in results {result.propertyID}]
		_unique:    list.UniqueItems(_resultIDs) & true
	})
})

#SelectionCutoverSnapshot: #ContextGraphSnapshot & {
	schema:     "kernel.context-graph.v0"
	snapshotID: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	modules: {"module.fixture": {kind: "repository", name: "fixture", rootNamespaceID: "namespace.fixture"}}
	namespaces: {
		"namespace.fixture": {moduleID: "module.fixture", parentNamespaceID: null, name: "fixture", kind: "repository-root", rootPath: "."}
	}
	members: {
		"member.inside":  {moduleID: "module.fixture", namespaceID: "namespace.fixture", name: "inside", kind: "file", path: "src/inside"}
		"member.outside": {moduleID: "module.fixture", namespaceID: "namespace.fixture", name: "outside", kind: "file", path: "other/outside"}
	}
	relationships: {}
	evidence:      {}
	provenance: {
		authorityDigest: "sha256:1111111111111111111111111111111111111111111111111111111111111111"
		schemaDigest:    "sha256:2222222222222222222222222222222222222222222222222222222222222222"
		hydratorDigest:  "sha256:3333333333333333333333333333333333333333333333333333333333333333"
	}
}

#SelectionCutoverRequest: #ContextApplicationRequest & {
	schema:       "dotfiles.context-application-request.v0"
	requestID:    "request.cutover"
	repository:   "fixture"
	revision:     "HEAD"
	allowedPaths: ["src"]
	overlayMode:  "disabled"
	roots:        {memberIDs: ["member.inside"], namespaceIDs: [], pathPrefixes: []}
}

#SelectionCutoverProofFixture: {
	schema:          "dotfiles.context-selection-proof.v0"
	snapshotID:      "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	frontier0:       {distance: 0, entities: []}
	frontier1:       {distance: 1, entities: []}
	frontier2:       {distance: 2, entities: []}
	frontier3:       {distance: 3, entities: []}
	frontier4:       {distance: 4, entities: []}
	frontier5:       {distance: 5, entities: []}
	frontier6:       {distance: 6, entities: []}
	frontier7:       {distance: 7, entities: []}
	frontier8:       {distance: 8, entities: []}
	selected:        [...#ContextEntityRef]
	relationshipIDs: [...#GraphID]
	evidenceIDs:     [...#GraphID]
	effectiveFiles:  [...#Path]
	counters: {
		modules: int & >=0, namespaces: int & >=0, members: int & >=0, entities: int & >=0
		files: int & >=0, fileBytes: int & >=0, relationships: int & >=0, evidence: int & >=0
	}
	contextDigest: "sha256:4444444444444444444444444444444444444444444444444444444444444444"
	packetDigest:  "sha256:5555555555555555555555555555555555555555555555555555555555555555"
}

contextSelectionCutoverFixtures: {
	boundary: {
		inside:        {request: #SelectionCutoverRequest, snapshot: #SelectionCutoverSnapshot, selected: [{kind: "member", id: "member.inside"}], files: ["src/inside"]}
		outsideMember: {request: #SelectionCutoverRequest, snapshot: #SelectionCutoverSnapshot, selected: [{kind: "member", id: "member.outside"}], files: []}
		outsideFile:   {request: #SelectionCutoverRequest, snapshot: #SelectionCutoverSnapshot, selected: [{kind: "member", id: "member.inside"}], files: ["other/outside"]}
		repositoryRoot: {
			request: #ContextApplicationRequest & {
				schema: "dotfiles.context-application-request.v0", requestID: "request.cutover-root", repository: "fixture", revision: "HEAD"
				allowedPaths: ["."], overlayMode: "disabled", roots: {memberIDs: ["member.inside"], namespaceIDs: [], pathPrefixes: []}
			}
			snapshot: #SelectionCutoverSnapshot
			selected: [{kind: "member", id: "member.inside"}, {kind: "member", id: "member.outside"}]
			files:    ["other/outside", "src/inside"]
		}
	}

	canonical: {
		proposal: #ContextRootProposal & {
			schema: "dotfiles.context-root-proposal.v0", requestID: "request.cutover"
			snapshotID: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
			memberIDs: ["member.a", "member.b"], namespaceIDs: [], pathPrefixes: ["src", "src/z"]
		}
		unsortedProposal: {
			schema: "dotfiles.context-root-proposal.v0", requestID: "request.cutover"
			snapshotID: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
			memberIDs: ["member.b", "member.a"], namespaceIDs: [], pathPrefixes: []
		}
		rootCatalog: #ContextRootCatalog & {
			schema: "dotfiles.context-root-catalog.v0", requestID: "request.cutover"
			snapshotID: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
			memberIDs: ["member.a", "member.b"], namespaceIDs: [], paths: ["src", "src/z"]
		}
		emptyProposal: #ContextRootProposal & {
			schema: "dotfiles.context-root-proposal.v0", requestID: "request.cutover"
			snapshotID: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
			memberIDs: [], namespaceIDs: [], pathPrefixes: []
		}
		emptyRootCatalog: #ContextRootCatalog & {
			schema: "dotfiles.context-root-catalog.v0", requestID: "request.cutover"
			snapshotID: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
			memberIDs: [], namespaceIDs: [], paths: []
		}
		aliases: []
		proof: #ContextSelectionProof & #SelectionCutoverProofFixture & {
			selected: [], relationshipIDs: ["rel.a", "rel.b"], evidenceIDs: ["evidence.a", "evidence.b"], effectiveFiles: ["src/a", "src/b"]
			counters: {modules: 0, namespaces: 0, members: 0, entities: 0, files: 2, fileBytes: 0, relationships: 2, evidence: 2}
		}
		duplicateEvidenceProof: #SelectionCutoverProofFixture & {
			selected: [], relationshipIDs: [], evidenceIDs: ["evidence.a", "evidence.a"], effectiveFiles: []
			counters: {modules: 0, namespaces: 0, members: 0, entities: 0, files: 0, fileBytes: 0, relationships: 0, evidence: 2}
		}
		empty: #ContextSelectionProof & #SelectionCutoverProofFixture & {
			selected: [], relationshipIDs: [], evidenceIDs: [], effectiveFiles: []
			counters: {modules: 0, namespaces: 0, members: 0, entities: 0, files: 0, fileBytes: 0, relationships: 0, evidence: 0}
		}
	}

	committed: {
		Projection=projection: #GitCommittedSnapshotProjection & {
			observation: {
				schema: "kernel.git-committed-snapshot-observation.v0", repositoryID: "repository.fixture"
				requestedRevision: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
				resolvedRevision: {format: "sha1", hex: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
				rootTree: {format: "sha1", hex: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}
				occurrences: [
					{path: "src", mode: "040000", kind: "tree", objectID: {format: "sha1", hex: "cccccccccccccccccccccccccccccccccccccccc"}},
					{path: "src/main.py", mode: "100644", kind: "blob", size: 12, objectID: {format: "sha1", hex: "dddddddddddddddddddddddddddddddddddddddd"}},
				]
				hydrator: {identity: "hydrator.fixture", digest: "sha256:6666666666666666666666666666666666666666666666666666666666666666"}
			}
			schemaDigest: "sha256:7777777777777777777777777777777777777777777777777777777777777777"
			policyDigest: "sha256:8888888888888888888888888888888888888888888888888888888888888888"
		}
		Request=request: #ContextApplicationRequest & {
			schema: "dotfiles.context-application-request.v0", requestID: "request.committed-cutover"
			repository: "repository.fixture", revision: "HEAD", allowedPaths: ["."], overlayMode: "disabled"
			roots: {memberIDs: [], namespaceIDs: [], pathPrefixes: ["src"]}
		}
		Proposal=proposal: #ContextRootProposal & {
			schema: "dotfiles.context-root-proposal.v0", requestID: Request.requestID, snapshotID: Projection.graph.snapshotID
			memberIDs: [], namespaceIDs: [], pathPrefixes: []
		}
		Policy=policy: #ContextSelectionPolicy & {schema: "dotfiles.context-selection-policy.v0", predicates: ["contains"], limits: {}}
		_qualificationEvaluation: #ContextCommittedSelectionEvaluation & {
			request: Request, proposal: Proposal, policy: Policy, committedProjection: Projection
		}
		outsideBoundary: {
			request: #ContextApplicationRequest & {
				schema: "dotfiles.context-application-request.v0", requestID: Request.requestID, repository: Request.repository, revision: Request.revision
				allowedPaths: ["src/main.py"], overlayMode: "disabled", roots: {memberIDs: [], namespaceIDs: [], pathPrefixes: ["src/main.py"]}
			}
			proposal: Proposal, policy: Policy, committedProjection: Projection
		}
	}
}

contextSelectionPropertyFixtures: {
	relationshipOutgoing: {
		snapshot: #SelectionPropertySnapshot & {
			members: {"member.root": #SelectionPropertyMember & {path: "src/root"}, "member.target": #SelectionPropertyMember & {path: "src/target"}}
			relationships: {"rel.out": {subject: {kind: "member", id: "member.root"}, predicate: "contains", object: {kind: "member", id: "member.target"}, evidenceIDs: []}}
		}
		predicates: ["contains"]
		previous: [{entity: {kind: "member", id: "member.root"}, distance: 0, direction: "root", predecessor: null}]
		visited: previous, distance: 1
	}
	relationshipOrderPerturbation: {
		first: contextSelectionPropertyFixtures.relationshipPredecessor
		second: contextSelectionPropertyFixtures.relationshipPredecessor & {
			snapshot: #SelectionPropertySnapshot & {
				members: contextSelectionPropertyFixtures.relationshipPredecessor.snapshot.members
				relationships: {
					"rel.z.out": contextSelectionPropertyFixtures.relationshipPredecessor.snapshot.relationships["rel.z.out"]
					"rel.a.in":  contextSelectionPropertyFixtures.relationshipPredecessor.snapshot.relationships["rel.a.in"]
				}
			}
		}
	}
	nonContains: {
		snapshot: #SelectionPropertySnapshot & {
			members: {"member.root": #SelectionPropertyMember & {path: "src/root"}, "member.target": #SelectionPropertyMember & {path: "src/target"}}
			relationships: {"rel.occurs": {subject: {kind: "member", id: "member.root"}, predicate: "occurs_as", object: {kind: "member", id: "member.target"}, evidenceIDs: []}}
		}
		predicates: ["contains"]
		previous: [{entity: {kind: "member", id: "member.root"}, distance: 0, direction: "root", predecessor: null}]
		visited: previous, distance: 1
	}
	endpointReversed: {
		snapshot: #SelectionPropertySnapshot & {
			members: {}
			relationships: {"rel.reversed": {subject: {kind: "namespace", id: "namespace.fixture"}, predicate: "contains", object: {kind: "module", id: "module.fixture"}, evidenceIDs: []}}
		}
		predicates: ["contains"]
		previous: [{entity: {kind: "module", id: "module.fixture"}, distance: 0, direction: "root", predecessor: null}]
		visited: previous, distance: 1
	}
}
