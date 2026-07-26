package contextmodel

#PropertyTargetDefinition:
	"#ContextGraphSnapshot" |
		"#ContextGraphResolution"

#PropertyMutationKind:
	"unknown-module-root" |
		"unknown-namespace-module" |
		"cross-module-parent" |
		"unknown-member-namespace" |
		"unknown-member-module" |
		"unknown-relationship-endpoint" |
		"unknown-evidence-reference" |
		"unknown-evidence-subject" |
		"unknown-evidence-producer" |
		"unknown-selection-entity" |
		"unknown-selection-seed" |
		"unknown-selection-relationship" |
		"unknown-selection-evidence" |
		"selection-snapshot-mismatch" |
		"closed-member-shape" |
		"elevate-observation-authority"

#PropertyExpectedResult: "accept" | "reject" | "accept-or-reject"

#ContextGraphProperty: close({
	id:               #GraphID
	description:      #NonEmptyString
	targetDefinition: #PropertyTargetDefinition
	mutation:         #PropertyMutationKind

	generator: close({
		profile:    "repository-context"
		minModules: int & >=1
		maxModules: int & >=minModules
		minMembers: int & >=1
		maxMembers: int & >=minMembers
	})

	expected: close({
		cue:      #PropertyExpectedResult
		pydantic: #PropertyExpectedResult
	})
})

#ContextGraphPropertyCatalog: close({
	schema: "kernel.context-properties.v0"
	properties: [ID=#GraphID]: #ContextGraphProperty & {
		id: ID
	}
})

contextGraphPropertyCatalog: #ContextGraphPropertyCatalog & {
	properties: {
		"module-root-resolves": {
			description:      "Every module root resolves to a namespace owned by that module."
			targetDefinition: "#ContextGraphSnapshot"
			mutation:         "unknown-module-root"
			generator:        {profile: "repository-context", minModules: 1, maxModules: 6, minMembers: 1, maxMembers: 12}
			expected:         {cue: "reject", pydantic: "accept-or-reject"}
		}

		"namespace-module-resolves": {
			description:      "Every namespace resolves to a known module."
			targetDefinition: "#ContextGraphSnapshot"
			mutation:         "unknown-namespace-module"
			generator:        {profile: "repository-context", minModules: 1, maxModules: 6, minMembers: 1, maxMembers: 12}
			expected:         {cue: "reject", pydantic: "accept-or-reject"}
		}
		"namespace-parent-same-module": {
			description:      "Namespace parents remain inside the child namespace module."
			targetDefinition: "#ContextGraphSnapshot"
			mutation:         "cross-module-parent"
			generator:        {profile: "repository-context", minModules: 2, maxModules: 6, minMembers: 1, maxMembers: 12}
			expected:         {cue: "reject", pydantic: "accept-or-reject"}
		}
		"member-namespace-same-module": {
			description:      "Members resolve to namespaces owned by the member module."
			targetDefinition: "#ContextGraphSnapshot"
			mutation:         "unknown-member-namespace"
			generator:        {profile: "repository-context", minModules: 1, maxModules: 6, minMembers: 1, maxMembers: 12}
			expected:         {cue: "reject", pydantic: "accept-or-reject"}
		}

		"member-module-resolves": {
			description:      "Every member resolves to a known module."
			targetDefinition: "#ContextGraphSnapshot"
			mutation:         "unknown-member-module"
			generator:        {profile: "repository-context", minModules: 1, maxModules: 6, minMembers: 1, maxMembers: 12}
			expected:         {cue: "reject", pydantic: "accept-or-reject"}
		}
		"relationship-endpoint-resolves": {
			description:      "Relationship endpoints resolve in the declared entity kind."
			targetDefinition: "#ContextGraphSnapshot"
			mutation:         "unknown-relationship-endpoint"
			generator:        {profile: "repository-context", minModules: 1, maxModules: 6, minMembers: 2, maxMembers: 12}
			expected:         {cue: "reject", pydantic: "accept-or-reject"}
		}
		"relationship-evidence-resolves": {
			description:      "Every relationship evidence reference resolves."
			targetDefinition: "#ContextGraphSnapshot"
			mutation:         "unknown-evidence-reference"
			generator:        {profile: "repository-context", minModules: 1, maxModules: 6, minMembers: 2, maxMembers: 12}
			expected:         {cue: "reject", pydantic: "accept-or-reject"}
		}

		"evidence-subject-resolves": {
			description:      "Evidence subjects resolve in the declared entity kind."
			targetDefinition: "#ContextGraphSnapshot"
			mutation:         "unknown-evidence-subject"
			generator:        {profile: "repository-context", minModules: 1, maxModules: 6, minMembers: 1, maxMembers: 12}
			expected:         {cue: "reject", pydantic: "accept-or-reject"}
		}
		"evidence-producer-resolves": {
			description:      "Evidence producers resolve when present."
			targetDefinition: "#ContextGraphSnapshot"
			mutation:         "unknown-evidence-producer"
			generator:        {profile: "repository-context", minModules: 1, maxModules: 6, minMembers: 1, maxMembers: 12}
			expected:         {cue: "reject", pydantic: "accept-or-reject"}
		}
		"selection-entity-resolves": {
			description:      "Selected entities resolve against the bound snapshot."
			targetDefinition: "#ContextGraphResolution"
			mutation:         "unknown-selection-entity"
			generator:        {profile: "repository-context", minModules: 1, maxModules: 6, minMembers: 1, maxMembers: 12}
			expected:         {cue: "reject", pydantic: "accept-or-reject"}
		}

		"selection-seed-resolves": {
			description:      "Seed entities resolve against the bound snapshot."
			targetDefinition: "#ContextGraphResolution"
			mutation:         "unknown-selection-seed"
			generator:        {profile: "repository-context", minModules: 1, maxModules: 6, minMembers: 1, maxMembers: 12}
			expected:         {cue: "reject", pydantic: "accept-or-reject"}
		}
		"selection-relationship-resolves": {
			description:      "Selected relationships resolve against the bound snapshot."
			targetDefinition: "#ContextGraphResolution"
			mutation:         "unknown-selection-relationship"
			generator:        {profile: "repository-context", minModules: 1, maxModules: 6, minMembers: 2, maxMembers: 12}
			expected:         {cue: "reject", pydantic: "accept-or-reject"}
		}
		"selection-evidence-resolves": {
			description:      "Selected evidence resolves against the bound snapshot."
			targetDefinition: "#ContextGraphResolution"
			mutation:         "unknown-selection-evidence"
			generator:        {profile: "repository-context", minModules: 1, maxModules: 6, minMembers: 1, maxMembers: 12}
			expected:         {cue: "reject", pydantic: "accept-or-reject"}
		}
		"selection-snapshot-binds": {
			description:      "A selection binds to exactly one graph snapshot."
			targetDefinition: "#ContextGraphResolution"
			mutation:         "selection-snapshot-mismatch"
			generator:        {profile: "repository-context", minModules: 1, maxModules: 6, minMembers: 1, maxMembers: 12}
			expected:         {cue: "reject", pydantic: "reject"}
		}
		"member-shape-closed": {
			description:      "Unknown member fields are rejected."
			targetDefinition: "#ContextGraphSnapshot"
			mutation:         "closed-member-shape"
			generator:        {profile: "repository-context", minModules: 1, maxModules: 6, minMembers: 1, maxMembers: 12}
			expected:         {cue: "reject", pydantic: "reject"}
		}
		"observation-authority-bounded": {
			description:      "Collected observations cannot claim controller or root authority."
			targetDefinition: "#ContextGraphSnapshot"
			mutation:         "elevate-observation-authority"
			generator:        {profile: "repository-context", minModules: 1, maxModules: 6, minMembers: 1, maxMembers: 12}
			expected:         {cue: "reject", pydantic: "reject"}
		}
	}
}
