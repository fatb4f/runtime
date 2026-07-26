package codexprofile

#PropertyMutationClass:
	"duplicate-coordinate" |
		"same-path-source-incarnation" |
		"replace-admitted-raw" |
		"elevate-authority" |
		"collapse-unavailable-to-null" |
		"timestamp-ordering" |
		"invalid-freshness" |
		"invalid-token-arithmetic" |
		"malformed-source-token-value" |
		"duplicate-diagnostic-code" |
		"replayed-strict-qualification" |
		"adapter-version-evolution" |
		"synthetic-lineage-over-native" |
		"merge-journal-lifecycle" |
		"non-collector-write" |
		"couple-policy-axes" |
		"omit-readiness" |
		"change-repository-identity" |
		"exceed-size-bound" |
		"nondeterministic-projection" |
		"discard-command-output" |
		"exceed-command-projection"

#PropertyExpectedResult: "accept" | "reject"

#ContractProperty: close({
	id:               #ID
	description:      #NonEmptyString
	targetDefinition: #NonEmptyString
	preconditions:    [...#NonEmptyString] & [_, ...]
	mutationClass:    #PropertyMutationClass
	preservedTerms:   [...#ID]
	changedTerms:     [...#ID] & [_, ...]
	expectedResult:   #PropertyExpectedResult
	rejectionCode:    #ID | null
})

#ContractPropertyCatalog: close({
	schema: "codex-profile-properties.v0"
	properties: [ID=#ID]: #ContractProperty & {id: ID}
})

#ExecutablePropertyCase: close({
	id:               #ID
	baseline:         #ID
	mutation:         #ID
	adapterOperation: "admit-handoff" | "project-handoff" | "admit-command-artifact" | "admit-command-result"
	expectedResult:   #PropertyExpectedResult
	rejectionCode:    #ID | null
	expectedProjectionDigests?: close({
		json:     #Digest
		markdown: #Digest
	})
})

#ExecutablePropertyCatalog: close({
	schema: "codex-profile-executable-properties.v0"
	cases: [ID=#ID]: #ExecutablePropertyCase & {id: ID}
})

#QualificationCase: close({
	id:                #ID
	mutationAttempted: bool
	actualResult:      #PropertyExpectedResult
	rejectionCode:     #ID | null
	status:            "passed"
	evidence:          #MutationEvidence
})

#MutationEvidence: close({
	valueChanged:     bool
	artifactsChanged: bool
	rawDigests:       [#Digest, #Digest]
	artifactDigests:  [#Digest, #Digest]
	jsonDigests?:     [#Digest, #Digest]
	markdownDigests?: [#Digest, #Digest]
})

#QualificationReport: close({
	schema:       "codex-profile-property-report.v0"
	declaredIDs:  [...#ID]
	generatedIDs: [...#ID]
	executedIDs:  [...#ID]
	reportedIDs:  [...#ID]
	cases:        [...#QualificationCase]
})

assertionCatalog: #ContractPropertyCatalog & {
	properties: {
		"source.identity-deduplication": {
			description:      "Physical identity is the source identity and byte offset; derived indexes cannot replace it."
			targetDefinition: "#RawObservationEnvelope"
			preconditions:    ["Two observations address one source coordinate."]
			mutationClass:    "duplicate-coordinate"
			preservedTerms:   ["source.identity", "source.offset"]
			changedTerms:     ["observation.id"]
			expectedResult:   "reject"
			rejectionCode:    "duplicate.physical-identity"
		}
		"source.append-only-admission": {
			description:      "Raw admission appends complete records and never replaces an admitted fact."
			targetDefinition: "#RawObservationEnvelope"
			preconditions:    ["A raw observation has already been admitted."]
			mutationClass:    "replace-admitted-raw"
			preservedTerms:   ["source.identity", "source.offset"]
			changedTerms:     ["payload.digest"]
			expectedResult:   "reject"
			rejectionCode:    "raw.not-append-only"
		}
		"source.incarnation-generation": {
			description:      "A same-path source replacement, truncation below the durable watermark, or checkpoint anchor mismatch receives a new source generation before reading."
			targetDefinition: "#SourceIdentity"
			preconditions:    ["A rollout path already has an admitted watermark."]
			mutationClass:    "same-path-source-incarnation"
			preservedTerms:   ["source.id"]
			changedTerms:     ["source.generation"]
			expectedResult:   "accept"
			rejectionCode:    null
		}
		"authority.provenance-bounded": {
			description:      "Observed facts retain their source authority and cannot self-promote to checkpoint or derived authority."
			targetDefinition: "#Provenance"
			preconditions:    ["The value originated at an observed source."]
			mutationClass:    "elevate-authority"
			preservedTerms:   ["source.coordinate"]
			changedTerms:     ["provenance.authority"]
			expectedResult:   "reject"
			rejectionCode:    "authority.elevation"
		}
		"facts.nullable-vs-unavailable": {
			description:      "Unavailable native facts carry a reason and are not collapsed into nullable backend fields."
			targetDefinition: "#AvailableUInt"
			preconditions:    ["A native fact was not observed."]
			mutationClass:    "collapse-unavailable-to-null"
			preservedTerms:   []
			changedTerms:     ["fact.availability"]
			expectedResult:   "reject"
			rejectionCode:    "fact.availability-lost"
		}
		"ordering.explicit-correlation-only": {
			description:      "Cross-source order requires an explicit admitted correlation edge; timestamps are diagnostic only."
			targetDefinition: "#CrossSourceOrderClaim"
			preconditions:    ["The coordinates belong to different sources."]
			mutationClass:    "timestamp-ordering"
			preservedTerms:   ["source.coordinates"]
			changedTerms:     ["correlation.edges"]
			expectedResult:   "reject"
			rejectionCode:    "ordering.missing-edge"
		}
		"checkpoint.freshness-categorical": {
			description:      "Checkpoint freshness is exactly exact, stale, invalid, or unknown; age cannot create a fifth validity state."
			targetDefinition: "#CheckpointFreshness"
			preconditions:    ["A checkpoint assessment is emitted."]
			mutationClass:    "invalid-freshness"
			preservedTerms:   ["checkpoint.id"]
			changedTerms:     ["checkpoint.freshness"]
			expectedResult:   "reject"
			rejectionCode:    "checkpoint.invalid-freshness"
		}
		"usage.token-accounting": {
			description:      "Token fields are nonnegative, cached input does not exceed reported input, and fresh input is their difference."
			targetDefinition: "#UsageObservation"
			preconditions:    ["A TokenCountEvent observation is normalized."]
			mutationClass:    "invalid-token-arithmetic"
			preservedTerms:   ["source.coordinate"]
			changedTerms:     ["usage.cached", "usage.fresh"]
			expectedResult:   "reject"
			rejectionCode:    "usage.invalid-accounting"
		}
		"usage.malformed-source-token-value": {
			description:      "Malformed token values from source evidence remain diagnostics and are not normalized as zero-valued usage."
			targetDefinition: "#UsageObservation"
			preconditions:    ["A source token usage object contains a present malformed token field."]
			mutationClass:    "malformed-source-token-value"
			preservedTerms:   ["source.coordinate"]
			changedTerms:     ["usage.field"]
			expectedResult:   "reject"
			rejectionCode:    "usage.invalid-accounting"
		}
		"diagnostic.identity-scoped": {
			description:      "Multiple diagnostics at one source coordinate with the same code remain separately admissible by scope or ordinal."
			targetDefinition: "#RawObservationEnvelope"
			preconditions:    ["One source coordinate emits more than one finding with the same diagnostic code."]
			mutationClass:    "duplicate-diagnostic-code"
			preservedTerms:   ["source.coordinate"]
			changedTerms:     ["diagnostic.scope", "diagnostic.ordinal"]
			expectedResult:   "accept"
			rejectionCode:    null
		}
		"strict.persisted-qualification": {
			description:      "Strict qualification reads persisted unresolved diagnostics for the active source and adapter version."
			targetDefinition: "#UsageObservation"
			preconditions:    ["A strict diagnostic has already been admitted for the active source and adapter version."]
			mutationClass:    "replayed-strict-qualification"
			preservedTerms:   ["source.coordinate", "adapter.identity"]
			changedTerms:     ["qualification.invocation"]
			expectedResult:   "reject"
			rejectionCode:    "usage.invalid-accounting"
		}
		"usage.adapter-version-addressed": {
			description:      "Normalized usage observations are addressed by adapter identity so corrected normalization can coexist with prior output."
			targetDefinition: "#UsageObservation"
			preconditions:    ["A source coordinate has already been normalized by a previous adapter version."]
			mutationClass:    "adapter-version-evolution"
			preservedTerms:   ["source.coordinate"]
			changedTerms:     ["adapter.identity"]
			expectedResult:   "accept"
			rejectionCode:    null
		}
		"lineage.native-migration": {
			description:      "Native context-window identity is retained; legacy numeric identity is represented only as window number."
			targetDefinition: "#ContextWindowObservation"
			preconditions:    ["Native lineage is present or a legacy record is migrated."]
			mutationClass:    "synthetic-lineage-over-native"
			preservedTerms:   ["thread.id", "window.number"]
			changedTerms:     ["window.identity"]
			expectedResult:   "reject"
			rejectionCode:    "lineage.native-identity-lost"
		}
		"journal.lifecycle-separated": {
			description:      "Hook start and completion remain separate immutable records and unresolved starts remain observable."
			targetDefinition: "#HookStarted|#HookCompleted"
			preconditions:    ["A hook invocation starts."]
			mutationClass:    "merge-journal-lifecycle"
			preservedTerms:   ["hook.transaction-id"]
			changedTerms:     ["journal.event-kind"]
			expectedResult:   "reject"
			rejectionCode:    "journal.lifecycle-collapsed"
		}
		"storage.collector-sole-writer": {
			description:      "Only the collector may issue a DuckDB write request."
			targetDefinition: "#DuckDBWriteRequest"
			preconditions:    ["A component requests a DuckDB mutation."]
			mutationClass:    "non-collector-write"
			preservedTerms:   ["run.id"]
			changedTerms:     ["storage.writer"]
			expectedResult:   "reject"
			rejectionCode:    "storage.non-collector-writer"
		}
		"policy.telemetry-recommendation-orthogonal": {
			description:      "Telemetry health and recommendation are independent fields; no state implies a recommendation."
			targetDefinition: "#PolicyAssessment"
			preconditions:    ["A policy assessment is projected."]
			mutationClass:    "couple-policy-axes"
			preservedTerms:   ["telemetry.state"]
			changedTerms:     ["policy.recommendation"]
			expectedResult:   "accept"
			rejectionCode:    null
		}
		"handoff.readiness-required": {
			description:      "Objective, current and next operations, and completion criteria are required and nonempty."
			targetDefinition: "#Handoff"
			preconditions:    ["A handoff is created."]
			mutationClass:    "omit-readiness"
			preservedTerms:   ["repository.identity"]
			changedTerms:     ["handoff.readiness"]
			expectedResult:   "reject"
			rejectionCode:    "handoff.not-ready"
		}
		"handoff.repository-identity": {
			description:      "The canonical repository root and HEAD revision identify the continuation workspace."
			targetDefinition: "#Handoff"
			preconditions:    ["Git repository discovery succeeded."]
			mutationClass:    "change-repository-identity"
			preservedTerms:   ["handoff.operations"]
			changedTerms:     ["repository.identity"]
			expectedResult:   "reject"
			rejectionCode:    "repository.identity-changed"
		}
		"handoff.size-bounded": {
			description:      "Canonical JSON and Markdown projections are each limited to 16 KiB."
			targetDefinition: "#Handoff"
			preconditions:    ["A validated handoff is projected."]
			mutationClass:    "exceed-size-bound"
			preservedTerms:   ["handoff.meaning"]
			changedTerms:     ["projection.bytes"]
			expectedResult:   "reject"
			rejectionCode:    "handoff.size-exceeded"
		}
		"handoff.projection-deterministic": {
			description:      "The same validated handoff produces identical canonical JSON and Markdown."
			targetDefinition: "#Handoff"
			preconditions:    ["Repository state and createdAt are held constant."]
			mutationClass:    "nondeterministic-projection"
			preservedTerms:   ["handoff.meaning"]
			changedTerms:     ["environment.order"]
			expectedResult:   "accept"
			rejectionCode:    null
		}
		"command.artifact-complete": {
			description:      "Complete stdout and stderr bytes remain retained with hashes regardless of projection."
			targetDefinition: "#CommandArtifactManifest"
			preconditions:    ["A child command was started or launch failure was normalized."]
			mutationClass:    "discard-command-output"
			preservedTerms:   ["command.argv"]
			changedTerms:     ["artifact.bytes"]
			expectedResult:   "reject"
			rejectionCode:    "command.output-discarded"
		}
		"command.projection-bounded": {
			description:      "The command result is at most 4 KiB and contains at most 20 relevant lines."
			targetDefinition: "#CommandResult"
			preconditions:    ["A trustworthy command artifact exists."]
			mutationClass:    "exceed-command-projection"
			preservedTerms:   ["artifact.identity"]
			changedTerms:     ["projection.bytes"]
			expectedResult:   "reject"
			rejectionCode:    "command.projection-exceeded"
		}
	}
}

// These case names are resolved by the typed mutation and operation registries.
// The data is exported verbatim and is the authoritative executable inventory.
handoffExecutableCatalog: #ExecutablePropertyCatalog & {
	cases: {
		"handoff.readiness-required": {
			baseline:         "handoff.valid"
			mutation:         "handoff.remove-readiness"
			adapterOperation: "admit-handoff"
			expectedResult:   "reject"
			rejectionCode:    "handoff.not-ready"
		}
		"handoff.repository-identity": {
			baseline:         "handoff.valid"
			mutation:         "handoff.change-repository"
			adapterOperation: "admit-handoff"
			expectedResult:   "reject"
			rejectionCode:    "repository.identity-changed"
		}
		"handoff.size-bounded": {
			baseline:         "handoff.valid"
			mutation:         "handoff.exceed-projection"
			adapterOperation: "project-handoff"
			expectedResult:   "reject"
			rejectionCode:    "handoff.size-exceeded"
		}
		"handoff.projection-deterministic": {
			baseline:         "handoff.valid"
			mutation:         "handoff.reorder-input"
			adapterOperation: "project-handoff"
			expectedResult:   "accept"
			rejectionCode:    null
			expectedProjectionDigests: {
				json:     "sha256:5cfbd3531bb3fc8c79d76eaaeaf2326a79e7661fee7905dd17aa1d5b15614516"
				markdown: "sha256:e5c4bf7af3ca3d73e527d9e61a5ca7608be4a0a42b86b145d8cb27aa51eb7dbd"
			}
		}
		"command.artifact-complete": {
			baseline:         "command.artifact-valid"
			mutation:         "command.remove-output"
			adapterOperation: "admit-command-artifact"
			expectedResult:   "reject"
			rejectionCode:    "command.output-discarded"
		}
		"command.projection-bounded": {
			baseline:         "command.result-valid"
			mutation:         "command.exceed-projection"
			adapterOperation: "admit-command-result"
			expectedResult:   "reject"
			rejectionCode:    "command.projection-exceeded"
		}
	}
}
