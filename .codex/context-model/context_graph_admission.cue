package contextmodel

// Authority-state values are transport fragments. An elevated effective state
// becomes authoritative only when it is closed by an admission transition in
// #ContextEvidenceAdmissionBundle.
#ContextEvidenceAuthorityState: close({
	schema:             "kernel.context-evidence-authority-state.v0"
	evidenceID:         #GraphID
	snapshotID:         #Digest
	Evidence=evidence:  #ContextEvidence & {payloadDigest: #ContentDigest}
	effectiveAuthority: #ClaimAuthority

	// Effective authority cannot be below the evidence's intrinsic authority.
	_effectiveAuthorityAllowed: #ContextAuthorityTransitionExpectations[Evidence.authority][effectiveAuthority] & "accept"
})

// Collection is a separate trust boundary. Every collector, including a
// source-fact collector, is restricted to none or candidate authority.
#ContextCollectedEvidenceEnvelope: close({
	schema: "kernel.context-evidence-collection.v0"
	// Keep collection authority as two concrete alternatives. Expressing the
	// equality through a plain disjunction leaves effectiveAuthority ambiguous
	// in CUE even after a concrete evidence value is unified downstream.
	state: (#ContextEvidenceAuthorityState & {
		evidence:           #ContextEvidence & {authority: "none"}
		effectiveAuthority: "none"
	}) | (#ContextEvidenceAuthorityState & {
		evidence:           #ContextEvidence & {authority: "candidate"}
		effectiveAuthority: "candidate"
	})
	admission: null
})

#ContextEvidenceAdmissionRecord: close({
	schema:           "kernel.context-evidence-admission-record.v0"
	admissionID:      #GraphID
	decisionDigest:   #Digest
	evidenceID:       #GraphID
	evidenceDigest:   #ContentDigest
	sourceSnapshotID: #Digest
	policyDigest:     #Digest
	actor:            #ContextEntityRef
	from:             #ClaimAuthority
	to:               #ClaimAuthority
})

#ContextAuthorityTransitionExpectedResult: "accept" | "reject"

// Authority may be preserved or increased, but never demoted. A preserved
// transition is the deterministic replay/idempotence case.
#ContextAuthorityTransitionExpectations: close({
	none: close({
		none:       "accept"
		candidate:  "accept"
		controller: "accept"
		root:       "accept"
	})
	candidate: close({
		none:       "reject"
		candidate:  "accept"
		controller: "accept"
		root:       "accept"
	})
	controller: close({
		none:       "reject"
		candidate:  "reject"
		controller: "accept"
		root:       "accept"
	})
	root: close({
		none:       "reject"
		candidate:  "reject"
		controller: "reject"
		root:       "accept"
	})
})

#ContextNoAdmissionTransitionExpectations: close({
	none: close({
		none:       "accept"
		candidate:  "reject"
		controller: "reject"
		root:       "reject"
	})
	candidate: close({
		none:       "reject"
		candidate:  "accept"
		controller: "reject"
		root:       "reject"
	})
	controller: close({
		none:       "reject"
		candidate:  "reject"
		controller: "accept"
		root:       "reject"
	})
	root: close({
		none:       "reject"
		candidate:  "reject"
		controller: "reject"
		root:       "accept"
	})
})

#ContextEvidenceNoAdmissionTransition: close({
	schema: "kernel.context-evidence-no-admission-transition.v0"
	Before=before: #ContextEvidenceAuthorityState & {
		BaseEvidence=evidence: #ContextEvidence & {payloadDigest: #ContentDigest}
		effectiveAuthority:    BaseEvidence.authority
	}
	after: #ContextEvidenceAuthorityState & {
		evidenceID:         Before.evidenceID
		snapshotID:         Before.snapshotID
		evidence:           Before.evidence
		effectiveAuthority: Before.effectiveAuthority
	}
	admission: null
})

#ContextEvidenceAdmissionTransition: close({
	schema:                    "kernel.context-evidence-admission-transition.v0"
	PolicyDigest=policyDigest: #Digest
	Before=before: #ContextEvidenceAuthorityState & {
		BaseEvidence=evidence: #ContextEvidence & {payloadDigest: #ContentDigest}
		effectiveAuthority:    BaseEvidence.authority
	}
	After=after: #ContextEvidenceAuthorityState & {
		evidenceID: Before.evidenceID
		snapshotID: Before.snapshotID
		evidence:   Before.evidence
	}
	admission: #ContextEvidenceAdmissionRecord & {
		evidenceID:       Before.evidenceID
		evidenceDigest:   Before.evidence.payloadDigest
		sourceSnapshotID: Before.snapshotID
		policyDigest:     PolicyDigest
		from:             Before.effectiveAuthority
		to:               After.effectiveAuthority
	}
	_transitionAllowed: #ContextAuthorityTransitionExpectations[Before.effectiveAuthority][After.effectiveAuthority] & "accept"
})

#ContextEvidenceAuthorityProjection: close({
	schema:         "kernel.context-evidence-authority-projection.v0"
	projectionKind: #GraphID
	Source=source:  #ContextEvidenceAuthorityState
	projected: #ContextEvidenceAuthorityState & {
		evidenceID:         Source.evidenceID
		snapshotID:         Source.snapshotID
		evidence:           Source.evidence
		effectiveAuthority: Source.effectiveAuthority
	}
})

#ContextEvidenceAdmissionBundle: close({
	schema: "kernel.context-evidence-admission-bundle.v0"
	states: [StateID=#GraphID]: #ContextEvidenceAuthorityState & {evidenceID: StateID}
	admissions: [AdmissionID=#GraphID]: #ContextEvidenceAdmissionTransition & {
		admission: admissionID: AdmissionID
	}

	// Every admission must materialize exactly its after-state in the state map.
	_admissionStateRefs: [for _, transition in admissions {
		[for stateID, state in states if stateID == transition.after.evidenceID {
			stateID:     stateID
			_stateMatch: state & transition.after
		}] & [_]
	}]

	// Every state that exceeds intrinsic evidence authority is backed by exactly
	// one qualifying transition whose complete after-state is identical.
	_elevatedStateAdmissionRefs: [for stateID, state in states if state.effectiveAuthority != state.evidence.authority {
		[for admissionID, transition in admissions if transition.after.evidenceID == stateID {
			admissionID: admissionID
			_stateMatch: state & transition.after
		}] & [_]
	}]
})

#ContextEvidenceAdmissionScenario:
	"no-admission" |
		"valid-admission" |
		"wrong-evidence-id" |
		"wrong-evidence-digest" |
		"wrong-snapshot" |
		"wrong-policy-digest" |
		"unknown-field"

#ContextEvidenceAdmissionCase: close({
	id:       #GraphID
	from:     #ClaimAuthority
	to:       #ClaimAuthority
	scenario: #ContextEvidenceAdmissionScenario
	expected: #ContextAuthorityTransitionExpectedResult
})

#ContextEvidenceAdmissionMatrix: close({
	schema: "kernel.context-evidence-admission-matrix.v0"
	cases: [ID=#GraphID]: #ContextEvidenceAdmissionCase & {id: ID}
})

#ContextEvidenceAdmissionScenarios: close({
	"no-admission":          true
	"valid-admission":       true
	"wrong-evidence-id":     true
	"wrong-evidence-digest": true
	"wrong-snapshot":        true
	"wrong-policy-digest":   true
	"unknown-field":         true
})

contextEvidenceAdmissionMatrix: #ContextEvidenceAdmissionMatrix & {
	cases: {
		for fromAuthority, transitionExpectations in #ContextAuthorityTransitionExpectations {
			for toAuthority, transitionExpected in transitionExpectations {
				for scenarioName, _ in #ContextEvidenceAdmissionScenarios {
					"admission.\(fromAuthority).\(toAuthority).\(scenarioName)": {
						id:       "admission.\(fromAuthority).\(toAuthority).\(scenarioName)"
						from:     fromAuthority
						to:       toAuthority
						scenario: scenarioName
						if scenarioName == "no-admission" {
							expected: #ContextNoAdmissionTransitionExpectations[fromAuthority][toAuthority]
						}
						if scenarioName == "valid-admission" {
							expected: transitionExpected
						}
						if scenarioName != "no-admission" && scenarioName != "valid-admission" {
							expected: "reject"
						}
					}
				}
			}
		}
	}
}
