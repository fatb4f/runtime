package sufficientwithgap

import positive "github.com/fatb4f/dotfiles/context-model/fixtures/positive:positive"

invalid: positive.base & {
	gaps: "gap.missing-source": {
		kind:                "missing-source"
		description:         "A required source remains unavailable."
		blocksSufficiency:   true
		requiredEvidenceIDs: []
	}
	sufficiency: state: "sufficient"
}
