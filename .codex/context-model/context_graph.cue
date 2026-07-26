package contextmodel

// Context graph kernel: a transport- and implementation-neutral repository
// inventory shared by base resolution, code intelligence, hydration, and
// downstream SBOM/DuckDB projections.

#GraphID:          #NonEmptyString & =~"^[a-z0-9]+([._:/-][a-z0-9]+)*$"
#GraphIDs:         [...#GraphID]
#NonEmptyGraphIDs: #GraphIDs & [_, ...]
#ContentDigest:    #NonEmptyString & =~"^[a-z0-9][a-z0-9._-]*:[0-9a-f]+$"

#GraphEntityKind: "module" | "namespace" | "member"

#ContextModuleKind:
	"repository" |
		"workspace" |
		"project" |
		"application"

#ContextNamespaceKind:
	"repository-root" |
		"source" |
		"configuration" |
		"contracts" |
		"package" |
		"application" |
		"workflow" |
		"generated" |
		"evidence" |
		"tests" |
		"tooling" |
		"language" |
		"plugin" |
		"controller"

#ContextMemberKind:
	"file" |
		"directory" |
		"module" |
		"package" |
		"contract" |
		"workflow" |
		"provider" |
		"entrypoint" |
		"cell" |
		"generated-artifact" |
		"external-component" |
		"documentation" |
		"test"

#ContextPredicate:
	"contains" |
		"depends_on" |
		"imports" |
		"requires" |
		"defines" |
		"consumes" |
		"produces" |
		"invokes" |
		"analyzes" |
		"validates" |
		"governs" |
		"generated_from" |
		"implemented_by" |
		"packaged_by" |
		"resolved_by" |
		"occurs_as" |
		"extension:" + #GraphID

#ContextEvidenceKind:
	"source" |
		"observation" |
		"diagnostic" |
		"attestation" |
		"validation-result"

#ContextEvidenceAuthority: {
	source:              #ClaimAuthority
	observation:         "none" | "candidate"
	diagnostic:          #ClaimAuthority
	attestation:         #ClaimAuthority
	"validation-result": #ClaimAuthority
}

#ContextEntityRef: close({
	kind: #GraphEntityKind
	id:   #GraphID
})

#ContextSourceRef: close({
	kind: #GraphID

	repository?:    #NonEmptyString
	revision?:      #NonEmptyString
	path?:          #Path
	contentDigest?: #ContentDigest

	properties?: [string]: _
})

#ContextModule: close({
	kind: #ContextModuleKind
	name: #NonEmptyString

	rootNamespaceID: #GraphID
	source?:         #ContextSourceRef
	properties?: [string]: _
})

#ContextNamespace: close({
	moduleID:          #GraphID
	parentNamespaceID: #GraphID | null

	name: #NonEmptyString
	kind: #ContextNamespaceKind

	rootPath?: #Path | "."
	language?: #GraphID
	source?:   #ContextSourceRef
	properties?: [string]: _
})

#ContextMember: close({
	moduleID:    #GraphID
	namespaceID: #GraphID

	name: #NonEmptyString
	kind: #ContextMemberKind

	path?:   #Path
	source?: #ContextSourceRef
	properties?: [string]: _
})

#ContextRelationship: close({
	subject:   #ContextEntityRef
	predicate: #ContextPredicate
	object:    #ContextEntityRef

	evidenceIDs: #GraphIDs
	properties?: [string]: _
})

#ContextEvidence: close({
	kind: #ContextEvidenceKind

	subject:  #ContextEntityRef | null
	producer: #ContextEntityRef | null
	source:   #ContextSourceRef

	authority:      #ContextEvidenceAuthority[kind]
	payloadDigest?: #ContentDigest

	diagnostics: [...close({
		code:    #GraphID
		message: #NonEmptyString
	})]
	properties?: [string]: _
})

#ContextGraphProvenance: close({
	authorityDigest: #Digest
	schemaDigest:    #Digest
	hydratorDigest:  #Digest

	baseRevision?:   #NonEmptyString
	baseTree?:       #NonEmptyString
	indexDigest?:    #Digest
	worktreeDigest?: #Digest
})

#ContextGraphSnapshot: close({
	schema:     "kernel.context-graph.v0"
	snapshotID: #Digest

	modules: [#GraphID]:       #ContextModule
	namespaces: [#GraphID]:    #ContextNamespace
	members: [#GraphID]:       #ContextMember
	relationships: [#GraphID]: #ContextRelationship
	evidence: [#GraphID]:      #ContextEvidence

	provenance: #ContextGraphProvenance

	_moduleIDs:       [for id, _ in modules {id}]
	_namespaceIDs:    [for id, _ in namespaces {id}]
	_memberIDs:       [for id, _ in members {id}]
	_relationshipIDs: [for id, _ in relationships {id}]
	_evidenceIDs:     [for id, _ in evidence {id}]

	// Every module root resolves to a namespace owned by that module.
	_moduleRootRefs: [for moduleID, module in modules {
		[for namespaceID, namespace in namespaces
		if namespaceID == module.rootNamespaceID && namespace.moduleID == moduleID {
			namespaceID
		}] & [_, ...]
	}]

	// Namespace parents stay inside the same module.
	_namespaceModuleRefs: [for _, namespace in namespaces {
		[for moduleID, _ in modules if moduleID == namespace.moduleID {moduleID}] & [_, ...]
	}]
	_namespaceParentRefs: [for _, namespace in namespaces if namespace.parentNamespaceID != null {
		[for parentID, parent in namespaces
		if parentID == namespace.parentNamespaceID && parent.moduleID == namespace.moduleID {
			parentID
		}] & [_, ...]
	}]

	// Members resolve to a module and one of that module's namespaces.
	_memberModuleRefs: [for _, member in members {
		[for moduleID, _ in modules if moduleID == member.moduleID {moduleID}] & [_, ...]
	}]
	_memberNamespaceRefs: [for _, member in members {
		[for namespaceID, namespace in namespaces
		if namespaceID == member.namespaceID && namespace.moduleID == member.moduleID {
			namespaceID
		}] & [_, ...]
	}]

	// Relationship endpoints and evidence references must resolve.
	_relationshipSubjectRefs: [for _, relationship in relationships {
		if relationship.subject.kind == "module" {
			[for id, _ in modules if id == relationship.subject.id {id}] & [_, ...]
		}
		if relationship.subject.kind == "namespace" {
			[for id, _ in namespaces if id == relationship.subject.id {id}] & [_, ...]
		}
		if relationship.subject.kind == "member" {
			[for id, _ in members if id == relationship.subject.id {id}] & [_, ...]
		}
	}]
	_relationshipObjectRefs: [for _, relationship in relationships {
		if relationship.object.kind == "module" {
			[for id, _ in modules if id == relationship.object.id {id}] & [_, ...]
		}
		if relationship.object.kind == "namespace" {
			[for id, _ in namespaces if id == relationship.object.id {id}] & [_, ...]
		}
		if relationship.object.kind == "member" {
			[for id, _ in members if id == relationship.object.id {id}] & [_, ...]
		}
	}]
	_relationshipEvidenceRefs: [for _, relationship in relationships {
		for evidenceID in relationship.evidenceIDs {
			[for id, _ in evidence if id == evidenceID {id}] & [_, ...]
		}
	}]

	// Evidence subjects and producers, when present, use the same entity space.
	_evidenceSubjectRefs: [for _, item in evidence if item.subject != null {
		if item.subject.kind == "module" {
			[for id, _ in modules if id == item.subject.id {id}] & [_, ...]
		}
		if item.subject.kind == "namespace" {
			[for id, _ in namespaces if id == item.subject.id {id}] & [_, ...]
		}
		if item.subject.kind == "member" {
			[for id, _ in members if id == item.subject.id {id}] & [_, ...]
		}
	}]
	_evidenceProducerRefs: [for _, item in evidence if item.producer != null {
		if item.producer.kind == "module" {
			[for id, _ in modules if id == item.producer.id {id}] & [_, ...]
		}
		if item.producer.kind == "namespace" {
			[for id, _ in namespaces if id == item.producer.id {id}] & [_, ...]
		}
		if item.producer.kind == "member" {
			[for id, _ in members if id == item.producer.id {id}] & [_, ...]
		}
	}]
})

#ContextGapRecord: close({
	description: #NonEmptyString
	blocking:    bool
})

#ContextConflictRecord: close({
	description: #NonEmptyString
	resolved:    bool
})

#ContextGraphSelection: close({
	schema:     "kernel.context-selection.v0"
	requestID:  #ID
	snapshotID: #Digest

	seedEntities: #NonEmptyContextEntityRefs
	selected:     #NonEmptyContextEntityRefs

	relationshipIDs: #GraphIDs
	evidenceIDs:     #GraphIDs
	gaps: [#GraphID]:      #ContextGapRecord
	conflicts: [#GraphID]: #ContextConflictRecord

	sufficiency: "insufficient" | "provisional" | "sufficient"

})

#NonEmptyContextEntityRefs: [...#ContextEntityRef] & [_, ...]

#ContextGraphResolution: close({
	schema:    "kernel.context-resolution.v0"
	snapshot:  #ContextGraphSnapshot
	selection: #ContextGraphSelection

	_snapshotIDMatch: selection.snapshotID & snapshot.snapshotID

	// Selection references resolve against the bound snapshot.
	_seedEntityRefs: [for entity in selection.seedEntities {
		if entity.kind == "module" {
			[for id, _ in snapshot.modules if id == entity.id {id}] & [_, ...]
		}
		if entity.kind == "namespace" {
			[for id, _ in snapshot.namespaces if id == entity.id {id}] & [_, ...]
		}
		if entity.kind == "member" {
			[for id, _ in snapshot.members if id == entity.id {id}] & [_, ...]
		}
	}]
	_selectedEntityRefs: [for entity in selection.selected {
		if entity.kind == "module" {
			[for id, _ in snapshot.modules if id == entity.id {id}] & [_, ...]
		}
		if entity.kind == "namespace" {
			[for id, _ in snapshot.namespaces if id == entity.id {id}] & [_, ...]
		}
		if entity.kind == "member" {
			[for id, _ in snapshot.members if id == entity.id {id}] & [_, ...]
		}
	}]
	_selectionRelationshipRefs: [for relationshipID in selection.relationshipIDs {
		[for id, _ in snapshot.relationships if id == relationshipID {id}] & [_, ...]
	}]
	_selectionEvidenceRefs: [for evidenceID in selection.evidenceIDs {
		[for id, _ in snapshot.evidence if id == evidenceID {id}] & [_, ...]
	}]
})
