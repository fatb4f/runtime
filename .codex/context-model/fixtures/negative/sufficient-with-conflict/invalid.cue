package sufficientwithconflict

import positive "github.com/fatb4f/dotfiles/context-model/fixtures/positive:positive"

invalid: positive.base & {
	conflicts: "conflict.source": {
		leftRef:     "hypothesis.context-model"
		rightRef:    "evidence.issue-54"
		description: "Source and inference remain inconsistent."
		evidenceIDs: ["evidence.issue-54"]
		resolution:  "unresolved"
	}
	sufficiency: state: "sufficient"
}
