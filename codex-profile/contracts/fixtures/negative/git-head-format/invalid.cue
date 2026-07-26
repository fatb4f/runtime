package negative

import profile "github.com/fatb4f/dotfiles/codexprofile"

invalid: profile.#RepositoryState & {
	repositoryID: "dotfiles"
	head: {state: "observed", value: {
		format: "sha1"
		hex:    "e535d6d69bcefbb2851eb706b41a2000cef85035ffff"
	}}
	worktreeDigest: "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
	dirty:          false
}
