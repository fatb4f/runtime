package contextmodel

// Provisional authority policy for the repository-context seed. Only source
// evidence may arrive with elevated authority. Collected evidence remains
// none or candidate until a later explicit admission transition is modeled.
#ContextEvidenceAuthorityPolicy: close({
	source:              #ClaimAuthority
	observation:         "none" | "candidate"
	diagnostic:          "none" | "candidate"
	attestation:         "none" | "candidate"
	"validation-result": "none" | "candidate"
})

// #ContextEvidence indexes #ContextEvidenceAuthority by kind, so this
// unification makes the named policy relation part of evidence validation.
#ContextEvidenceAuthority: #ContextEvidenceAuthorityPolicy

#ContextEvidenceAuthorityExpectedResult: "accept" | "reject"

#ContextEvidenceAuthorityCase: close({
	id:        #GraphID
	kind:      #ContextEvidenceKind
	authority: #ClaimAuthority
	expected:  #ContextEvidenceAuthorityExpectedResult
})

#ContextEvidenceAuthorityMatrix: close({
	schema: "kernel.context-evidence-authority-matrix.v0"
	cases: [ID=#GraphID]: #ContextEvidenceAuthorityCase & {
		id: ID
	}
})

#ContextEvidenceAuthorityExpectations: close({
	source: close({
		none:       "accept"
		candidate:  "accept"
		controller: "accept"
		root:       "accept"
	})
	observation: close({
		none:       "accept"
		candidate:  "accept"
		controller: "reject"
		root:       "reject"
	})
	diagnostic: close({
		none:       "accept"
		candidate:  "accept"
		controller: "reject"
		root:       "reject"
	})
	attestation: close({
		none:       "accept"
		candidate:  "accept"
		controller: "reject"
		root:       "reject"
	})
	"validation-result": close({
		none:       "accept"
		candidate:  "accept"
		controller: "reject"
		root:       "reject"
	})
})

// Exhaustive executable projection of the kind × authority relation.
contextEvidenceAuthorityMatrix: #ContextEvidenceAuthorityMatrix & {
	cases: {
		for evidenceKind, authorityExpectations in #ContextEvidenceAuthorityExpectations {
			for authorityLevel, expectedResult in authorityExpectations {
				"authority.\(evidenceKind).\(authorityLevel)": {
					id:        "authority.\(evidenceKind).\(authorityLevel)"
					kind:      evidenceKind
					authority: authorityLevel
					expected:  expectedResult
				}
			}
		}
	}
}

// A classification-only change without admission must preserve every evidence
// field other than kind, including authority. This is the first metamorphic
// authority property; the full admission lifecycle is deferred.
#ContextEvidenceKindOnlyTransition: close({
	schema: "kernel.context-evidence-kind-transition.v0"
	before: #ContextEvidence
	after: #ContextEvidence & {
		subject:     before.subject
		producer:    before.producer
		source:      before.source
		authority:   before.authority
		diagnostics: before.diagnostics
	}
	admissionID: null
})
