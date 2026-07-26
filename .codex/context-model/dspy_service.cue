package contextmodel

import "strings"

// Provisional transport-neutral authority for DSPy/Codex inference. Backends
// propose candidate decisions; the Marimo workbook retains evidence admission,
// sufficiency derivation, and projection commitment authority.

#DspyCorrelation: close({
	sessionID: #NonEmptyString
	turnID:    #NonEmptyString
	role:      "correlation_only"
})

#DspyInferenceDeadline: close({
	budgetMs:           int & >=100 & <=9000
	interruptReserveMs: int & >=100 & <=2000

	_totalMs: budgetMs + interruptReserveMs
	_totalMs: <=9500
})

#DspyInferenceExpectations: close({
	dspyProgramDigest:    #Digest
	decisionSchemaDigest: #Digest
	serviceConfigDigest:  #Digest
})

#DspyCodeIntelRoute: close({
	id:           #ID
	language:     #ID
	globs:        [...#NonEmptyString]
	provider:     #ID
	typeOverlays: [...#ID]
})

#DspyProviderRoutingDocument: close({
	schema:     "code-intel.provider-routing.v1" | "factory.plugin-bundle.code-intel.lsp.provider-routing.v1"
	reference?: true
	authority?: false
	routes:     [...#DspyCodeIntelRoute]
})

#DspyCodeIntelTool: close({
	id:        #ID
	server:    #ID
	inputs:    close({[#ID]: #NonEmptyString})
	outputs:   close({[#ID]: #NonEmptyString})
	authority: false
})

#DspyToolRegistryDocument: close({
	schema:          "factory.plugin-bundle.code-intel.mcp.tool-registry.v1"
	reference:       true
	authority:       false
	defaultReadOnly: true
	tools:           [...#DspyCodeIntelTool]
})

#DspyCodeIntelEntrypoint: close({
	id:           #ID
	language:     #ID
	path:         #Path
	domain:       #ID
	provider:     #ID
	typeOverlays: [...#ID]
	authority:    #ID
})

#DspyCodeIntelProvider: close({
	id:           #ID
	kind:         #ProviderKind
	paths:        [...#Path]
	authority:    false
	evidenceOnly: true
})

#DspyCodeIntelStep: close({
	order:     int & >0
	id:        #ID
	goal:      #NonEmptyString
	authority: #ID
})

#DspyCodeIntelAuthorityBoundary: close({
	owns:       [...#NonEmptyString]
	doesNotOwn: [...#NonEmptyString]
})

#DspyCodeIntelWorkflowDocument: close({
	schema:      "factory.plugin-bundle.code-intel.lua-first-workflow.v1"
	id:          #ID
	intent:      #NonEmptyString
	entrypoints: [...#DspyCodeIntelEntrypoint]
	providers:   [...#DspyCodeIntelProvider]
	steps:       [...#DspyCodeIntelStep]
	authority:   #DspyCodeIntelAuthorityBoundary
})

#DspyCodeIntelDocument:
	#DspyProviderRoutingDocument |
		#DspyToolRegistryDocument |
		#DspyCodeIntelWorkflowDocument

#DspyInferenceInputs: close({
	request:      close(#ContextRequest)
	inventory:    close(#ContextInventory)
	observations: close({[#ID]: close(#SourceObservation)})
	evidence:     close({[#ID]: close(#Evidence)})
	codeIntel:    close({[#Path]: #DspyCodeIntelDocument})
})

#DspyDecisionSelection: {
	reason:      #NonEmptyString
	evidenceIDs: [#ID]
}

#DspyFragmentDecisionSelection: close({
	#DspyDecisionSelection
	ids: [...#ID]
})

#DspyFileDecisionSelection: close({
	#DspyDecisionSelection
	ids: [...#Path]
})

#DspyProviderDecisionSelection: close({
	#DspyDecisionSelection
	ids: [...#ID]
})

#DspyWorkflowDecisionSelection: close({
	#DspyDecisionSelection
	ids: [...#ID]
})

// This mirrors the strict Python ContextDecision transport. It intentionally
// excludes observations, admitted state, sufficiency summaries, and projections.
#ContextDecision: close({
	hypotheses: close({
		[#ID]: #ContextHypothesis & {
			evidenceIDs: [#ID]
		}
	})
	fragments: #DspyFragmentDecisionSelection
	files:     #DspyFileDecisionSelection
	providers: #DspyProviderDecisionSelection
	workflows: #DspyWorkflowDecisionSelection
	gaps:      close({[#ID]: #ContextGap})
	conflicts: close({
		[#ID]: #ContextConflict & {
			evidenceIDs: [#ID]
		}
	})
	sufficiencyState:   "insufficient" | "provisional" | "sufficient"
	sufficiencyReasons: [...#NonEmptyString] & [_, ...]
})

#DspyExecutionSurfaceKind:
	"app_run" |
		"stdio_oneshot" |
		"marimo_http_sse" |
		"typed_http_sse" |
		"unix_socket" |
		"a2a_http_sse"

#DspyBackendKind:    "codex" | "recorded"
#DspyCodexTransport: "openai_codex_python_sdk" | "codex_cli" | "recorded"
#DspyThreadMode:     "fresh_ephemeral" | "not_applicable"

#DspyRuntimeIdentityBase: {
	serviceID:             #ID
	serviceVersion:        #NonEmptyString
	dspyProgramDigest:     #Digest
	decisionSchemaDigest:  #Digest
	serviceConfigDigest:   #Digest
	model:                 #NonEmptyString
	reasoningEffort:       "minimal" | "low" | "medium" | "high" | "xhigh"
	executionSurface:      #DspyExecutionSurfaceKind
	threadPersisted:       false
	parentThreadInherited: false
}

#DspyCodexRuntimeIdentity: close({
	#DspyRuntimeIdentityBase
	backendKind:         "codex"
	openaiCodexVersion:  #NonEmptyString
	codexRuntimeVersion: #NonEmptyString
	codexTransport:      "openai_codex_python_sdk" | "codex_cli"
	sdkManagedAppServer: bool
	persistentClient:    bool
	threadMode:          "fresh_ephemeral"
})

#DspyRecordedRuntimeIdentity: close({
	#DspyRuntimeIdentityBase
	backendKind:         "recorded"
	codexTransport:      "recorded"
	sdkManagedAppServer: false
	persistentClient:    false
	threadMode:          "not_applicable"
})

#DspyRuntimeIdentity: #DspyCodexRuntimeIdentity | #DspyRecordedRuntimeIdentity

#DspyQueueState: close({
	depth:              int & >=0
	capacity:           int & >0
	activeTurns:        int & >=0
	maxConcurrentTurns: int & >0

	depth:       <=capacity
	activeTurns: <=maxConcurrentTurns
})

#DspyFailureKind:
	"deadline_exceeded" |
		"interrupted" |
		"busy" |
		"service_unavailable" |
		"authentication_unavailable" |
		"schema_mismatch" |
		"invalid_model_output" |
		"request_rejected" |
		"runtime_error"

#DspyFailurePhase: "queue" | "startup" | "inference" | "validation" | "shutdown"

#DspyTransportFailure: close({
	kind:            #DspyFailureKind
	phase:           #DspyFailurePhase
	message:         #NonEmptyString
	retryable:       bool
	diagnosticCode?: #ID
})

#DspyInferenceResultBase: {
	requestID:   #ID
	correlation: #DspyCorrelation
	inputDigest: #Digest
	runtime:     #DspyRuntimeIdentity
	queue:       #DspyQueueState
	durationMs:  int & >=0
}

#DspyInferenceCompleted: close({
	#DspyInferenceResultBase
	schema:            "dotfiles.dspy-inference-result.v0"
	status:            "completed"
	candidateDecision: #ContextDecision
})

#DspyInferenceFailed: close({
	#DspyInferenceResultBase
	schema:  "dotfiles.dspy-inference-result.v0"
	status:  "failed"
	failure: #DspyTransportFailure
})

#DspyInferenceResult: #DspyInferenceCompleted | #DspyInferenceFailed

#DspyInferenceRequest: close({
	schema:      "dotfiles.dspy-inference-request.v0"
	requestID:   #ID
	_requestID:  requestID
	correlation: #DspyCorrelation
	deadline:    #DspyInferenceDeadline
	expected:    #DspyInferenceExpectations
	inputDigest: #Digest
	inputs: #DspyInferenceInputs & {
		request: {requestID: _requestID}
	}

	_observationIDs: [for observationID, _ in inputs.observations {observationID}]
	_evidenceIDs:    [for evidenceID, _ in inputs.evidence {evidenceID}]

	_evidenceObservationRefs: [for _, item in inputs.evidence {
		for observationID in item.observationIDs {
			[for knownID in _observationIDs if knownID == observationID {knownID}] & [_, ...]
		}
	}]
	_codeIntelPathRefs: [for path, _ in inputs.codeIntel {
		[for allowedPath in inputs.request.allowedPaths if allowedPath == "." || path == allowedPath || strings.HasPrefix(path, allowedPath + "/") {allowedPath}] & [_, ...]
	}]
})

// Validation relation joining one closed request to one closed backend result.
// It is not transmitted, so hidden referential derivations remain local.
#DspyInferenceExchange: {
	request: #DspyInferenceRequest
	result: #DspyInferenceResult & {
		requestID:   request.requestID
		correlation: request.correlation
		inputDigest: request.inputDigest
		runtime: {
			serviceID:            "dspy-codexd"
			dspyProgramDigest:    request.expected.dspyProgramDigest
			decisionSchemaDigest: request.expected.decisionSchemaDigest
			serviceConfigDigest:  request.expected.serviceConfigDigest
		}
	}

	if result.status == "completed" {
		_candidate:            result.candidateDecision
		_inventoryFragmentIDs: [for fragmentID, _ in request.inputs.inventory.fragments {fragmentID}]
		_inventoryProviderIDs: [for providerID, _ in request.inputs.inventory.providers {providerID}]
		_inventoryWorkflowIDs: [for workflowID, _ in request.inputs.inventory.workflows {workflowID}]
		_evidenceIDs:          [for evidenceID, _ in request.inputs.evidence {evidenceID}]

		_fragmentRefs: [for fragmentID in _candidate.fragments.ids {
			[for knownID in _inventoryFragmentIDs if knownID == fragmentID {knownID}] & [_, ...]
		}]
		_providerRefs: [for providerID in _candidate.providers.ids {
			[for knownID in _inventoryProviderIDs if knownID == providerID {knownID}] & [_, ...]
		}]
		_workflowRefs: [for workflowID in _candidate.workflows.ids {
			[for knownID in _inventoryWorkflowIDs if knownID == workflowID {knownID}] & [_, ...]
		}]
		_fileBoundaryRefs: [for path in _candidate.files.ids {
			[for allowedPath in request.inputs.request.allowedPaths if allowedPath == "." || path == allowedPath || strings.HasPrefix(path, allowedPath + "/") {allowedPath}] & [_, ...]
		}]
		_decisionEvidenceRefs: [
			for group in [_candidate.fragments, _candidate.files, _candidate.providers, _candidate.workflows] {
				for evidenceID in group.evidenceIDs {
					[for knownID in _evidenceIDs if knownID == evidenceID {knownID}] & [_, ...]
				}
			},
			for _, hypothesis in _candidate.hypotheses {
				for evidenceID in hypothesis.evidenceIDs {
					[for knownID in _evidenceIDs if knownID == evidenceID {knownID}] & [_, ...]
				}
			},
			for _, conflict in _candidate.conflicts {
				for evidenceID in conflict.evidenceIDs {
					[for knownID in _evidenceIDs if knownID == evidenceID {knownID}] & [_, ...]
				}
			},
		]
	}
}

#DspyServiceIsolation: close({
	sandbox:                 "read_only"
	approvalMode:            "deny_all"
	hooksEnabled:            false
	shellEnabled:            false
	unifiedExecEnabled:      false
	toolsEnabled:            false
	appsEnabled:             false
	mcpEnabled:              false
	webSearchEnabled:        false
	multiAgentEnabled:       false
	browserEnabled:          false
	computerEnabled:         false
	imageGenerationEnabled:  false
	inheritUserInstructions: false
})

#DspyInferenceContract: close({
	schema:            "dotfiles.dspy-inference-contract.v0"
	requestSchema:     "dotfiles.dspy-inference-request.v0"
	resultSchema:      "dotfiles.dspy-inference-result.v0"
	oneTerminalResult: true
	candidateOnly:     true
	deadlineRequired:  true
})

#DspyBackendRuntimeBase: {
	threadPersisted:       false
	parentThreadInherited: false
}

#DspyCodexBackendRuntime: close({
	#DspyBackendRuntimeBase
	backendKind:         "codex"
	codexTransport:      "openai_codex_python_sdk" | "codex_cli"
	sdkManagedAppServer: bool
	persistentClient:    bool
	threadMode:          "fresh_ephemeral"
})

#DspyRecordedBackendRuntime: close({
	#DspyBackendRuntimeBase
	backendKind:         "recorded"
	codexTransport:      "recorded"
	sdkManagedAppServer: false
	persistentClient:    false
	threadMode:          "not_applicable"
})

#DspyBackendRuntime: #DspyCodexBackendRuntime | #DspyRecordedBackendRuntime

#DspyReadinessBase: {
	dspyProgramLoaded:    true
	isolationApplied:     true
	accountAuthenticated: bool
	sdkClientInitialized: bool
}

#DspyCodexReadiness: close({
	#DspyReadinessBase
	accountAuthenticated: true
	sdkClientInitialized: true
})

#DspyRecordedReadiness: close({
	#DspyReadinessBase
	accountAuthenticated: false
	sdkClientInitialized: false
})

#DspyBackendConfigBase: {
	schema:    "dotfiles.dspy-codex-backend-config.v0"
	serviceID: "dspy-codexd"
	contract:  #DspyInferenceContract
	limits: close({
		maxRequestBytes:    int & >=1024 & <=1048576
		maxResponseBytes:   int & >=1024 & <=1048576
		maxInferenceMs:     int & >=100 & <=9000
		maxQueueDepth:      int & >=0 & <=128
		maxConcurrentTurns: int & >0 & <=16
	})
	isolation: #DspyServiceIsolation
}

#DspyCodexBackendConfig: close({
	#DspyBackendConfigBase
	runtime:               #DspyCodexBackendRuntime
	readinessRequirements: #DspyCodexReadiness
})

#DspyRecordedBackendConfig: close({
	#DspyBackendConfigBase
	runtime:               #DspyRecordedBackendRuntime
	readinessRequirements: #DspyRecordedReadiness
})

#DspyBackendConfig: #DspyCodexBackendConfig | #DspyRecordedBackendConfig

// Backward-compatible definition name. The v0 socket-bound shape is replaced
// by the transport-neutral backend configuration above.
#DspyServiceConfig: #DspyBackendConfig

#DspyExecutionSurfaceBase: {
	schema:    "dotfiles.dspy-execution-surface.v0"
	surfaceID: #ID
	status:    "candidate" | "qualified" | "selected"
	contract: close({
		requestSchema: "dotfiles.dspy-inference-request.v0"
		resultSchema:  "dotfiles.dspy-inference-result.v0"
	})
}

#DspyAppRunSurface: close({
	#DspyExecutionSurfaceBase
	kind: "app_run"
	capabilities: close({
		crossProcess:         false
		persistent:           false
		streaming:            false
		cancellable:          bool
		localOnly:            true
		fixedEntrypoint:      true
		arbitraryCodeAllowed: false
	})
	deployment: close({
		supervisor:            "none"
		readinessNotification: false
	})
})

#DspyCrossProcessSurface: close({
	#DspyExecutionSurfaceBase
	kind: "stdio_oneshot" | "marimo_http_sse" | "typed_http_sse" | "unix_socket" | "a2a_http_sse"
	capabilities: close({
		crossProcess:         true
		persistent:           bool
		streaming:            bool
		cancellable:          bool
		localOnly:            bool
		fixedEntrypoint:      bool
		arbitraryCodeAllowed: bool
	})
	deployment: close({
		supervisor:            "s6"
		readinessNotification: bool
	})
})

#DspyExecutionSurfaceProjection: #DspyAppRunSurface | #DspyCrossProcessSurface
