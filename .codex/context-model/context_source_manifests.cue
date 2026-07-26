package contextmodel

#RevisionBoundSourceManifest: close({
	version: #NonEmptyString
	paths:   [#Path, ...#Path]
})

contextSchemaSources: #RevisionBoundSourceManifest & {
	version: "context-schema-sources.v2"
	paths: [
		".codex/context-model/context_graph.cue",
		".codex/context-model/context_selection_cutover_hardening.cue",
		".codex/context-model/context_selection_service.cue",
		".codex/context-model/git_committed_snapshot.cue",
		".codex/context-model/git_overlay.cue",
		".codex/context-model/model.cue",
	]
}

contextPolicySources: #RevisionBoundSourceManifest & {
	version: "context-policy-sources.v2"
	paths: [
		".codex/context-model/context_graph_authority.cue",
		".codex/context-model/context_graph_properties.cue",
		".codex/context-model/context_selection_cutover_hardening.cue",
		".codex/context-model/context_selection_service.cue",
	]
}

gitHydratorSources: #RevisionBoundSourceManifest & {
	version: "git-hydrator-sources.v1"
	paths: [
		".codex/context-hydrators/git/cmd/context-git-hydrator/main.go",
		".codex/context-hydrators/git/go.mod",
		".codex/context-hydrators/git/go.sum",
		".codex/context-hydrators/git/internal/hydrator/hydrator.go",
		".codex/context-hydrators/git/internal/hydrator/json.go",
		".codex/context-hydrators/git/internal/hydrator/observation.go",
		".codex/context-hydrators/git/internal/hydrator/overlay.go",
		".codex/context-hydrators/git/internal/hydrator/overlay_observation.go",
		".codex/context-hydrators/git/internal/hydrator/overlay_properties.go",
		".codex/context-hydrators/git/internal/hydrator/overlay_request.go",
		".codex/context-hydrators/git/internal/hydrator/overlay_types.go",
		".codex/context-hydrators/git/internal/hydrator/properties.go",
		".codex/context-hydrators/git/internal/hydrator/request.go",
		".codex/context-hydrators/git/internal/hydrator/types.go",
		".codex/context-hydrators/git/internal/identity/identity.go",
	]
}

graphServiceSources: #RevisionBoundSourceManifest & {
	version: "graph-service-sources.v2"
	paths: [
		".codex/context-model/context_selection_cutover_hardening.cue",
		".codex/context-model/context_selection_service.cue",
		".codex/context-model/context_source_manifests.cue",
		".codex/context-workbook/src/context_workbook/graph_service.py",
		".codex/context-workbook/src/context_workbook/models.py",
		".codex/context-workbook/src/context_workbook/repository.py",
	]
}
