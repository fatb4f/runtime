package codexprofile

import (
	"list"
	"strings"
	"time"
)

// CUE is the authority for issue #72 admission and policy boundaries. Runtime
// adapters may narrow these definitions, but may not widen them.

#NonEmptyString: string & !=""
#ID:             #NonEmptyString & =~"^[a-z0-9]+([._-][a-z0-9]+)*$"
#Digest:         string & =~"^sha256:[0-9a-f]{64}$"
#UUIDv7:         string & =~"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
#Timestamp:      time.Time
#GitRevision:    string & (=~"^[0-9a-f]{40}$" | =~"^[0-9a-f]{64}$")
#BoundedStrings: [...#NonEmptyString] & list.MaxItems(256)

#Handoff: close({
	schema:     "codex.handoff.v0"
	createdAt:  #Timestamp
	objective:  #NonEmptyString
	invariants: #BoundedStrings
	decisions:  #BoundedStrings
	repository: close({
		root:        #NonEmptyString
		revision:    #GitRevision
		branch:      #NonEmptyString | null
		dirtyPaths:  #BoundedStrings
		stagedPaths: #BoundedStrings
	})
	validation: close({
		passing: #BoundedStrings
		failing: #BoundedStrings
		notRun:  #BoundedStrings
	})
	currentOperation:   #NonEmptyString
	nextOperation:      #NonEmptyString
	completionCriteria: #BoundedStrings & [_, ...]
	evidencePointers:   #BoundedStrings
	openQuestions:      #BoundedStrings
})

#CommandResult: close({
	schema:        "codex.command-result.v0"
	exitCode:      int
	signal:        uint | null
	truncated:     bool
	relevantLines: [...string] & list.MaxItems(20)
	artifact:      #NonEmptyString
	sha256:        string & =~"^[0-9a-f]{64}$"
})

#CommandArtifactManifest: close({
	schema:           "codex.command-artifact.v0"
	argv:             [#NonEmptyString, ...string] & list.MaxItems(4096)
	workingDirectory: #NonEmptyString
	startedAt:        #Timestamp
	durationSeconds:  number & >=0
	exitCode:         int
	signal:           uint | null
	stdoutBytes:      uint
	stderrBytes:      uint
	stdoutSha256:     string & =~"^[0-9a-f]{64}$"
	stderrSha256:     string & =~"^[0-9a-f]{64}$"
})

#CommandQuarantine: close({
	schema:            "codex.command-quarantine.v0"
	argv:              [#NonEmptyString, ...string] & list.MaxItems(4096)
	workingDirectory:  #NonEmptyString
	startedAt:         #Timestamp
	durationSeconds:   number & >=0
	exitCode:          int
	signal:            uint | null
	stdoutBytes:       uint
	stderrBytes:       uint
	stdoutSha256:      string & =~"^[0-9a-f]{64}$"
	stderrSha256:      string & =~"^[0-9a-f]{64}$"
	manifestAvailable: bool
	failurePhase:      "artifact-admission" | "projection" | "result-admission" | "publication"
	failureCode:       #NonEmptyString
	failureDetail:     string & strings.MaxRunes(2048)
})

#GitObjectID: close({
	format: "sha1"
	hex:    string & =~"^[0-9a-f]{40}$"
}) | close({
	format: "sha256"
	hex:    string & =~"^[0-9a-f]{64}$"
})

#SourceKind: "rollout" | "checkpoint" | "hook_journal" | "wrapper_journal" | "app_server"
#Authority:  "upstream_observation" | "explicit_checkpoint" | "local_observation" | "derived"
#SourceID:   #Digest

#SourceIdentity: close({
	kind:       #SourceKind
	sourceID:   #SourceID
	generation: uint
	segmentID?: #UUIDv7
})

// Physical source identity is never replaced by a derived ordinal or index.
#SourceCoordinate: close({
	source:       #SourceIdentity
	sourceOffset: uint
})

#SourceCheckpoint: close({
	sourceID:         #SourceID
	sourceGeneration: uint
	nextOffset:       uint
	anchorStart:      uint & <=nextOffset
	anchorEnd:        nextOffset
	anchorDigest:     #Digest
})

#AdapterIdentity: close({
	adapterID: #ID
	version:   #NonEmptyString
	digest:    #Digest
})

#ProjectionIdentity: close({
	projectionID: #ID
	version:      #NonEmptyString
	digest:       #Digest
})

#UpstreamSourceCoordinate:     #SourceCoordinate & {source: {kind: "rollout" | "app_server"}}
#CheckpointSourceCoordinate:   #SourceCoordinate & {source: {kind: "checkpoint"}}
#LocalJournalSourceCoordinate: #SourceCoordinate & {source: {kind: "hook_journal" | "wrapper_journal"}}

#Provenance: close({
	authority: "upstream_observation"
	source:    #UpstreamSourceCoordinate
	adapter?:  #AdapterIdentity
}) | close({
	authority: "explicit_checkpoint"
	source:    #CheckpointSourceCoordinate
	adapter?:  #AdapterIdentity
}) | close({
	authority: "local_observation"
	source:    #LocalJournalSourceCoordinate
	adapter?:  #AdapterIdentity
})

#RunContract: close({
	schema: "codex-profile-run.v0"
	runID:  #UUIDv7
	repository: close({
		root:     #NonEmptyString
		revision: #NonEmptyString
	})
	codexVersion:   #NonEmptyString
	clientVersion:  #NonEmptyString
	model:          #NonEmptyString
	reasoningLevel: #NonEmptyString
	toolSchemaDigests: [#ID]: #Digest
	instructionsDigest: #Digest
	projectedConfig:    #Digest
	effectiveConfig:    #AvailableDigest
	validationCommands: [...#NonEmptyString] & [_, ...]
	successCriteria:    [...#NonEmptyString] & [_, ...]
})

#ObservedUInt:    close({state: "observed", value: uint})
#UnavailableUInt: close({state: "unavailable", reason: #NonEmptyString})
#AvailableUInt:   #ObservedUInt | #UnavailableUInt

#ObservedDigest:    close({state: "observed", value: #Digest})
#UnavailableDigest: close({state: "unavailable", reason: #NonEmptyString})
#AvailableDigest:   #ObservedDigest | #UnavailableDigest

#ObservedGitObjectID:    close({state: "observed", value: #GitObjectID})
#UnavailableGitObjectID: close({state: "unavailable", reason: #NonEmptyString})
#AvailableGitObjectID:   #ObservedGitObjectID | #UnavailableGitObjectID

#ObservedUUID:    close({state: "observed", value: #UUIDv7})
#UnavailableUUID: close({state: "unavailable", reason: #NonEmptyString})
#AvailableUUID:   #ObservedUUID | #UnavailableUUID

#RawObservationEnvelope: close({
	schema:        "codex-raw-observation.v0"
	observationID: #UUIDv7
	coordinate:    #SourceCoordinate
	observedAt:    #Timestamp
	mediaType:     "application/json"
	rawBytes:      uint
	payloadDigest: #Digest
	provenance:    #Provenance
	retainedPayload?: close({
		policyID:      #ID
		redacted:      true
		mediaType:     #NonEmptyString
		content:       string
		contentDigest: #Digest
	})
	admission: close({
		operation:        "append"
		deduplicationKey: coordinate
	})
})

#RepositoryState: close({
	repositoryID:   #ID
	head:           #AvailableGitObjectID
	worktreeDigest: #Digest
	dirty:          bool
})

#Checkpoint: close({
	schema:              "codex-checkpoint.v0"
	checkpointID:        #UUIDv7
	checkpointVersion:   uint
	operationGeneration: uint
	createdAt:           #Timestamp
	writer:              #AdapterIdentity
	repository:          #RepositoryState
	objective:           #NonEmptyString
	admittedDecisions:   [...#NonEmptyString]
	currentOperation?:   #NonEmptyString
	failures:            [...#NonEmptyString]
	nextOperation?:      #NonEmptyString
	redactionPolicy:     #ID
	contentDigest:       #Digest
})

#CheckpointFreshness: "exact" | "stale" | "invalid" | "unknown"

#CheckpointAssessment: close({
	checkpointID: #UUIDv7
	freshness:    #CheckpointFreshness
	reasons:      [...#NonEmptyString] & [_, ...]
})

#HookEventName: "preCompact" | "postCompact" | "sessionStart" | "stop" | "sessionEnd"

#HookStarted: close({
	schema:            "codex-hook-started.v0"
	hookTransactionID: #UUIDv7
	segmentID:         #UUIDv7
	sourceOffset:      uint
	localSequence:     uint
	sessionID:         #NonEmptyString
	turnID?:           #NonEmptyString
	hookEventName:     #HookEventName
	trigger?:          "manual" | "auto"
	source?:           #NonEmptyString
	handlerID:         #AdapterIdentity
	hookSchemaVersion: #NonEmptyString
	configFingerprint: #Digest
	rolloutWatermark?: #SourceCoordinate
	checkpointID?:     #UUIDv7
	observedAt:        #Timestamp
})

#HookCompleted: close({
	schema:              "codex-hook-completed.v0"
	hookTransactionID:   #UUIDv7
	segmentID:           #UUIDv7
	sourceOffset:        uint
	localSequence:       uint
	completedAt:         #Timestamp
	elapsedMilliseconds: uint
	exitStatus:          int
	outputDisposition:   "continued" | "advisory" | "failed_open"
	failureKind?:        #ID
})

#WrapperObservation: close({
	schema:               "codex-wrapper-observation.v0"
	wrapperTransactionID: #UUIDv7
	coordinate:           #SourceCoordinate
	logicalOperation:     #ID
	startedAt:            #Timestamp
	completedAt?:         #Timestamp
	rawOutputBytes:       uint
	modelVisibleBytes:    #AvailableUInt
	provenance:           #Provenance
})

#UsageObservation: close({
	schema:                       "codex-usage-observation.v0"
	observationID:                #UUIDv7
	threadID:                     #NonEmptyString
	rolloutOrdinal:               uint
	usageObservationIndex:        uint
	eventTimestamp:               #Timestamp
	Reported=reportedInputTokens: uint
	Cached=cachedInputTokens:     uint & <=Reported
	cacheWriteInputTokens:        uint
	freshInputTokens:             Reported - Cached
	outputTokens:                 uint
	reasoningOutputTokens:        uint
	totalTokens:                  uint
	estimatedContextPressure:     #AvailableUInt
	nativeActiveContextTokens:    #AvailableUInt
	modelContextWindow:           #AvailableUInt
	coordinate:                   #SourceCoordinate
	adapter:                      #AdapterIdentity
})

#RateLimitWindow: close({
	usedPercent:   number & >=0 & <=100
	windowMinutes: #AvailableUInt
	resetsAt:      #Timestamp | null
})

#RateLimitObservation: close({
	schema:               "codex-rate-limit-observation.v0"
	observationID:        #UUIDv7
	observedAt:           #Timestamp
	limitID:              #NonEmptyString | null
	limitName:            #NonEmptyString | null
	primary:              #RateLimitWindow | null
	secondary:            #RateLimitWindow | null
	creditsAvailable:     bool | null
	spendControlReached:  bool | null
	rateLimitReachedType: #NonEmptyString | null
	planType:             #NonEmptyString | null
	coordinate:           #SourceCoordinate
	adapter:              #AdapterIdentity
})

#TransitionKind: "summaryReplacement" | "freshWindowReset" | "legacyUnknown"

#ContextWindowObservation: close({
	schema:                  "codex-context-window-observation.v0"
	observationID:           #UUIDv7
	threadID:                #NonEmptyString
	windowNumber:            uint
	firstWindowID:           #AvailableUUID
	previousWindowID:        #AvailableUUID
	windowID:                #AvailableUUID
	identitySource:          "native" | "legacy_unavailable"
	transitionKind:          #TransitionKind
	replacementHistoryItems: #AvailableUInt
	coordinate:              #SourceCoordinate
	adapter:                 #AdapterIdentity

	if identitySource == "native" {
		firstWindowID: #ObservedUUID
		windowID:      #ObservedUUID
	}
	if identitySource == "legacy_unavailable" {
		firstWindowID:    #UnavailableUUID
		previousWindowID: #UnavailableUUID
		windowID:         #UnavailableUUID
		transitionKind:   "legacyUnknown"
	}
})

// A cross-source ordering claim requires an explicit edge. Timestamps are not
// admitted as ordering evidence.
#CorrelationEvidenceKind: "turn_id" | "rollout_watermark" | "checkpoint_id" | "hook_transaction_id" | "native_window_lineage"
#CorrelationEdge: close({
	from:     #SourceCoordinate
	to:       #SourceCoordinate
	evidence: #CorrelationEvidenceKind
	value:    #NonEmptyString
})
#CrossSourceOrderClaim: close({
	before: #SourceCoordinate
	after:  #SourceCoordinate
	edge: #CorrelationEdge & {
		from: before
		to:   after
	}
})

#CohortContract: close({
	schema:            "codex-cohort.v0"
	cohortID:          #ID
	controlDimensions: [...#ID]
	match: close({
		repositoryRevision:         #NonEmptyString
		taskContractDigest:         #Digest
		model:                      #NonEmptyString
		reasoningLevel:             #NonEmptyString
		codexVersion:               #NonEmptyString
		clientVersion:              #NonEmptyString
		toolSchemaDigest:           #Digest
		instructionsDigest:         #Digest
		effectiveConfigFingerprint: #AvailableDigest
		validationDigest:           #Digest
		successCriteriaDigest:      #Digest
	})
	taskSuccessRequired:          true
	validationSuccessRequired:    true
	evidenceCompletenessRequired: true
})

#TelemetryState: "healthy" | "degraded" | "unavailable"
#Recommendation: "none" | "checkpoint" | "compact" | "newSession"

// No implication couples telemetry state to recommendation. They are separate
// axes, so degraded/unavailable telemetry may correctly recommend none.
#PolicyAssessment: close({
	schema:                "codex-policy-assessment.v0"
	telemetryState:        #TelemetryState
	recommendation:        #Recommendation
	reasons:               [...#NonEmptyString]
	projection:            #ProjectionIdentity
	advisoryOnly:          true
	blockNativeCompaction: false
})

#DuckDBWriteRequest: close({
	schema:    "codex-duckdb-write.v0"
	writer:    "collector"
	operation: "append_raw" | "append_normalized" | "publish_projection"
	runID:     #UUIDv7
})
